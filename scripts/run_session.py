#!/usr/bin/env python3
"""Run the strategy game loop and record arena snapshots.

Loop model:
  * Каждые POLL_INTERVAL секунд (env: POLL_INTERVAL, default 0.5) делаем GET /api/arena.
  * Если arena.nextTurnIn > LATENCY_AVG и в этом turnNo мы ещё не
    отправляли команду — принимаем решение и POST /api/command.
  * Один turnNo = не более одной команды.
  * Никаких ретраев: ошибки просто логируются.
  * Сессия уникальна по id плантации с isMain: true.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from cherviak.client import GameClient
from cherviak.config import Config, load_config
from cherviak.strategies import LateralStrategy, PassiveStrategy


DEFAULT_OUTPUT_DIR = Path("artifacts/sessions")
STRATEGIES = {
    PassiveStrategy.name: PassiveStrategy,
    LateralStrategy.name: LateralStrategy,
}


def available_strategy_names() -> list[str]:
    return sorted(STRATEGIES)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Игровой цикл раннера: пишет arena/logs и (опционально) отправляет команды."
    )
    parser.add_argument(
        "--strategy",
        choices=available_strategy_names(),
        help="Имя стратегии для запуска.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Корневая директория сессий. По умолчанию {DEFAULT_OUTPUT_DIR}.",
    )
    parser.add_argument(
        "--logs-interval",
        type=float,
        default=5.0,
        help="Как часто запрашивать /api/logs.",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Разрешить отправку команд стратегии. По умолчанию — только запись истории.",
    )
    args = parser.parse_args()

    if args.strategy is None:
        parser.print_usage(sys.stderr)
        print("\nНе выбрана стратегия. Доступные стратегии:", file=sys.stderr)
        for strategy_name in available_strategy_names():
            print(f"  - {strategy_name}", file=sys.stderr)
        parser.exit(2)

    return args


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def serialize(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True)
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: serialize(val) for key, val in value.items()}
    if isinstance(value, list):
        return [serialize(item) for item in value]
    return value


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def looks_like_active_arena(arena: Any) -> bool:
    width, height = arena.size
    return width > 0 and height > 0


def find_hq_id(arena: Any) -> str | None:
    for plantation in arena.plantations:
        if plantation.is_main:
            return plantation.id
    return None


@dataclass
class SessionWriter:
    """Создаёт session_<hqId>/ когда видит HQ, пишет turns.jsonl и logs.jsonl."""

    root: Path
    strategy_name: str
    submit: bool
    latency_avg: float
    poll_interval: float
    base_url: str
    hq_id: str | None = None
    session_dir: Path | None = None
    turns_path: Path | None = None
    logs_path: Path | None = None

    def ensure_for_hq(self, hq_id: str) -> bool:
        """Switch to session dir for the given HQ id. Returns True if it changed."""
        if self.hq_id == hq_id:
            return False
        self.hq_id = hq_id
        session_dir = self.root / f"session_{hq_id}"
        session_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir = session_dir
        self.turns_path = session_dir / "turns.jsonl"
        self.logs_path = session_dir / "logs.jsonl"
        meta_path = session_dir / "meta.json"
        if not meta_path.exists():
            meta = {
                "startedAt": utc_now(),
                "hqId": hq_id,
                "strategy": self.strategy_name,
                "submit": self.submit,
                "baseUrl": self.base_url,
                "latencyAvg": self.latency_avg,
                "pollInterval": self.poll_interval,
            }
            meta_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return True


def describe_command_status(
    command: dict[str, Any] | None,
    submit_enabled: bool,
    response: dict[str, Any] | None,
) -> str:
    if command is None:
        return "none"
    if not submit_enabled:
        return "planned"
    if not isinstance(response, dict):
        return "failed"
    status_code = response.get("statusCode")
    if status_code is not None:
        return f"http_{status_code}"
    if response.get("error"):
        return "failed"
    if response.get("errors"):
        return "sent_with_errors"
    return "sent"


def format_position(position: list[int]) -> str:
    return f"[{position[0]},{position[1]}]"


def summarize_construction(arena: Any) -> str:
    if not arena.construction:
        return "0"
    items = [f"{format_position(item.position)}={item.progress}" for item in arena.construction[:3]]
    if len(arena.construction) > 3:
        items.append(f"+{len(arena.construction) - 3} more")
    return f"{len(arena.construction)}:{','.join(items)}"


def summarize_decision(command: dict[str, Any] | None) -> str:
    if not command:
        return "-"
    actions = command.get("command") or []
    targets: list[str] = []
    for action in actions[:3]:
        path = action.get("path") if isinstance(action, dict) else None
        if isinstance(path, list) and len(path) >= 3 and isinstance(path[2], list) and len(path[2]) == 2:
            targets.append(format_position(path[2]))
        else:
            targets.append("?")
    if len(actions) > 3:
        targets.append(f"+{len(actions) - 3}")

    relocate = command.get("relocateMain")
    relocate_summary = "-"
    if isinstance(relocate, list) and len(relocate) >= 2:
        relocate_summary = f"{format_position(relocate[0])}->{format_position(relocate[1])}"

    upgrade = command.get("plantationUpgrade") or "-"
    target_summary = ",".join(targets) if targets else "-"
    return (
        f"actions={len(actions)} "
        f"targets={target_summary} "
        f"relocate={relocate_summary} "
        f"upgrade={upgrade}"
    )


def summarize_response_errors(response: dict[str, Any] | None) -> str:
    if not isinstance(response, dict):
        return "-"
    errors = response.get("errors")
    if not errors:
        return "-"
    messages = [str(item) for item in errors[:2]]
    if len(errors) > 2:
        messages.append(f"+{len(errors) - 2}")
    return " | ".join(messages)


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("cherviak.client").setLevel(logging.DEBUG)
    logging.getLogger("cherviak.client.arena_raw").setLevel(logging.INFO)


async def decide_and_submit(
    strategy: Any,
    client: GameClient,
    arena: Any,
    submit: bool,
    turns_path: Path,
) -> None:
    """Синхронно считает решение и (при submit) отправляет его."""
    decision_started_at = time.perf_counter()
    command = strategy.decide_turn(arena)
    decision_elapsed_ms = (time.perf_counter() - decision_started_at) * 1000

    response: dict[str, Any] | None = None
    submit_elapsed_ms = 0.0
    if submit and command:
        submit_started_at = time.perf_counter()
        try:
            response = await asyncio.to_thread(client.post_command, command)
        except httpx.HTTPStatusError as exc:
            response = {
                "error": str(exc),
                "statusCode": exc.response.status_code,
                "body": exc.response.text,
            }
        except httpx.HTTPError as exc:
            response = {"error": str(exc)}
        submit_elapsed_ms = (time.perf_counter() - submit_started_at) * 1000

    strategy.on_turn_result(arena, command, response)
    command_status = describe_command_status(command, submit, response)
    construction_status = summarize_construction(arena)
    decision_summary = summarize_decision(command)
    response_errors = summarize_response_errors(response)
    append_jsonl(
        turns_path,
        {
            "capturedAt": utc_now(),
            "kind": "turn",
            "turnNo": arena.turn_no,
            "nextTurnIn": arena.next_turn_in,
            "strategyElapsedMs": round(decision_elapsed_ms, 3),
            "submitElapsedMs": round(submit_elapsed_ms, 3),
            "arena": serialize(arena),
            "decision": command,
            "response": response,
        },
    )
    logging.info(
        "turn=%s nextTurnIn=%.3f decision_ms=%.1f submit_ms=%.1f plantations=%s cells=%s construction=%s decision=%s command=%s errors=%s",
        arena.turn_no,
        arena.next_turn_in,
        decision_elapsed_ms,
        submit_elapsed_ms,
        len(arena.plantations),
        len(arena.cells),
        construction_status,
        decision_summary,
        command_status,
        response_errors,
    )


async def logs_loop(
    config: Config,
    session_writer: SessionWriter,
    interval: float,
    stop_event: asyncio.Event,
) -> None:
    """Опрашивает /api/logs независимо от игрового цикла."""
    seen_log_keys: set[tuple[str, str]] = set()
    with GameClient(config, log_requests=False) as client:
        while not stop_event.is_set():
            logs_path = session_writer.logs_path
            if logs_path is not None:
                try:
                    logs = await asyncio.to_thread(client.get_logs)
                except httpx.HTTPStatusError as exc:
                    append_jsonl(
                        logs_path,
                        {
                            "capturedAt": utc_now(),
                            "kind": "logs_error",
                            "statusCode": exc.response.status_code,
                            "body": exc.response.text,
                        },
                    )
                except httpx.HTTPError as exc:
                    append_jsonl(
                        logs_path,
                        {
                            "capturedAt": utc_now(),
                            "kind": "logs_error",
                            "error": str(exc),
                        },
                    )
                else:
                    for item in logs:
                        key = (str(item.get("time", "")), str(item.get("message", "")))
                        if key in seen_log_keys:
                            continue
                        seen_log_keys.add(key)
                        append_jsonl(
                            logs_path,
                            {
                                "capturedAt": utc_now(),
                                "kind": "log",
                                "entry": item,
                            },
                        )

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                pass


async def play_loop(
    client: GameClient,
    strategy: Any,
    session_writer: SessionWriter,
    submit: bool,
    latency_avg: float,
    poll_interval: float,
) -> None:
    """Главный игровой цикл. Тик длится poll_interval секунд."""
    last_submitted_turn: int | None = None
    active_round = False

    while True:
        tick_started = time.perf_counter()

        try:
            arena = await asyncio.to_thread(client.get_arena)
        except httpx.HTTPStatusError as exc:
            logging.warning(
                "arena fetch failed status=%s body=%s",
                exc.response.status_code,
                exc.response.text.strip(),
            )
            if session_writer.turns_path is not None:
                append_jsonl(
                    session_writer.turns_path,
                    {
                        "capturedAt": utc_now(),
                        "kind": "http_error",
                        "statusCode": exc.response.status_code,
                        "body": exc.response.text,
                    },
                )
            await _sleep_remaining(tick_started, poll_interval)
            continue
        except httpx.HTTPError as exc:
            logging.warning("arena fetch failed: %s", exc)
            if session_writer.turns_path is not None:
                append_jsonl(
                    session_writer.turns_path,
                    {
                        "capturedAt": utc_now(),
                        "kind": "network_error",
                        "error": str(exc),
                    },
                )
            await _sleep_remaining(tick_started, poll_interval)
            continue

        if not looks_like_active_arena(arena):
            if active_round and session_writer.turns_path is not None:
                append_jsonl(
                    session_writer.turns_path,
                    {
                        "capturedAt": utc_now(),
                        "kind": "round_finished",
                        "lastTurnNo": last_submitted_turn,
                    },
                )
                logging.info("round finished (last turn %s)", last_submitted_turn)
            active_round = False
            last_submitted_turn = None
            await _sleep_remaining(tick_started, poll_interval)
            continue

        hq_id = find_hq_id(arena)
        if hq_id is None:
            logging.info(
                "turn=%s nextTurnIn=%.3f no HQ plantation — waiting",
                arena.turn_no,
                arena.next_turn_in,
            )
            await _sleep_remaining(tick_started, poll_interval)
            continue

        switched = session_writer.ensure_for_hq(hq_id)
        if switched:
            logging.info(
                "session opened: hqId=%s dir=%s",
                hq_id,
                session_writer.session_dir,
            )
            strategy.on_round_started()
            append_jsonl(
                session_writer.turns_path,
                {
                    "capturedAt": utc_now(),
                    "kind": "round_started",
                    "hqId": hq_id,
                    "turnNo": arena.turn_no,
                    "arena": serialize(arena),
                },
            )
            active_round = True
            last_submitted_turn = None

        if not active_round:
            active_round = True

        if arena.next_turn_in <= latency_avg:
            logging.info(
                "turn=%s nextTurnIn=%.3f <= latencyAvg=%.3f — skip",
                arena.turn_no,
                arena.next_turn_in,
                latency_avg,
            )
            append_jsonl(
                session_writer.turns_path,
                {
                    "capturedAt": utc_now(),
                    "kind": "skip",
                    "turnNo": arena.turn_no,
                    "nextTurnIn": arena.next_turn_in,
                    "reason": "late",
                    "latencyAvg": latency_avg,
                },
            )
        elif last_submitted_turn == arena.turn_no:
            logging.debug(
                "turn=%s already submitted — skip",
                arena.turn_no,
            )
        else:
            await decide_and_submit(
                strategy,
                client,
                arena,
                submit,
                session_writer.turns_path,
            )
            last_submitted_turn = arena.turn_no

        await _sleep_remaining(tick_started, poll_interval)


async def _sleep_remaining(tick_started: float, poll_interval: float) -> None:
    elapsed = time.perf_counter() - tick_started
    remaining = poll_interval - elapsed
    if remaining > 0:
        await asyncio.sleep(remaining)


async def main_async() -> int:
    configure_logging()
    args = parse_args()
    config = load_config()
    strategy = STRATEGIES[args.strategy]()

    session_writer = SessionWriter(
        root=args.output_dir,
        strategy_name=strategy.name,
        submit=args.submit,
        latency_avg=config.latency_avg,
        poll_interval=config.poll_interval,
        base_url=config.base_url,
    )

    print(
        f"Sessions root: {args.output_dir} "
        f"(каждая сессия — session_<hqId>, poll={config.poll_interval}s, latencyAvg={config.latency_avg}s)"
    )

    stop_event = asyncio.Event()
    logs_task = asyncio.create_task(
        logs_loop(config, session_writer, args.logs_interval, stop_event)
    )

    try:
        with GameClient(config, log_requests=True) as client:
            await play_loop(
                client,
                strategy,
                session_writer,
                submit=args.submit,
                latency_avg=config.latency_avg,
                poll_interval=config.poll_interval,
            )
    finally:
        stop_event.set()
        try:
            await asyncio.wait_for(logs_task, timeout=2.0)
        except asyncio.TimeoutError:
            logs_task.cancel()

    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
