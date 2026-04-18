#!/usr/bin/env python3
"""Run the strategy game loop and record arena snapshots.

Loop model:
  * Каждые POLL_INTERVAL секунд (env: POLL_INTERVAL, default 0.5) делаем GET /api/arena.
  * Если arena.nextTurnIn > LATENCY_AVG и в этом turnNo мы ещё не
    отправляли команду — принимаем решение и POST /api/command.
  * Один turnNo = не более одной команды.
  * Никаких ретраев: ошибки просто логируются.
  * Сессия живёт, пока HQ не исчезнет надолго или не появится заново слишком далеко.
  * `hqId` записывается только для диагностики и не управляет границей сессии.
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
ARENA_INACTIVE_GRACE_TICKS = 3
HQ_MISSING_GRACE_TICKS = 3
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


def utc_now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


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


def find_hq_position(arena: Any) -> list[int] | None:
    for plantation in arena.plantations:
        if plantation.is_main:
            return list(plantation.position)
    return None


def is_relocate_position(previous_position: list[int], current_position: list[int]) -> bool:
    dx = abs(previous_position[0] - current_position[0])
    dy = abs(previous_position[1] - current_position[1])
    return (dx == 0 and dy == 0) or (dx == 1 and dy == 0) or (dx == 0 and dy == 1)


@dataclass
class SessionWriter:
    """Создаёт time-based session dir и пишет turns.jsonl/logs.jsonl."""

    root: Path
    strategy_name: str
    submit: bool
    latency_avg: float
    poll_interval: float
    base_url: str
    session_index: int = 0
    initial_hq_id: str | None = None
    current_hq_id: str | None = None
    initial_hq_position: list[int] | None = None
    current_hq_position: list[int] | None = None
    session_dir: Path | None = None
    turns_path: Path | None = None
    logs_path: Path | None = None

    def _allocate_session_dir(self, hq_position: list[int]) -> Path:
        suffix = utc_now_slug()
        x, y = hq_position
        self.session_index += 1
        candidate = self.root / f"session_{suffix}_{self.session_index:03d}_{x}_{y}"
        serial = 1
        while candidate.exists():
            serial += 1
            candidate = self.root / f"session_{suffix}_{self.session_index:03d}_{x}_{y}_{serial}"
        return candidate

    def open_round(self, hq_id: str, hq_position: list[int]) -> bool:
        """Open a new session dir for the round. Returns True if it was opened."""
        if self.session_dir is not None:
            return False
        self.initial_hq_id = hq_id
        self.current_hq_id = hq_id
        self.initial_hq_position = list(hq_position)
        self.current_hq_position = list(hq_position)
        session_dir = self._allocate_session_dir(hq_position)
        session_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir = session_dir
        self.turns_path = session_dir / "turns.jsonl"
        self.logs_path = session_dir / "logs.jsonl"
        meta_path = session_dir / "meta.json"
        if not meta_path.exists():
            meta = {
                "startedAt": utc_now(),
                "hqId": hq_id,
                "initialHqId": hq_id,
                "initialHqPosition": hq_position,
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

    def note_hq(
        self,
        hq_id: str,
        hq_position: list[int],
    ) -> tuple[bool, bool, str | None, list[int] | None]:
        """Update current HQ state inside the active round."""
        previous_hq_id = self.current_hq_id
        previous_hq_position = self.current_hq_position
        self.current_hq_id = hq_id
        self.current_hq_position = list(hq_position)
        return (
            previous_hq_id != hq_id,
            previous_hq_position != hq_position,
            previous_hq_id,
            previous_hq_position,
        )

    def close_round(self) -> None:
        self.initial_hq_id = None
        self.current_hq_id = None
        self.initial_hq_position = None
        self.current_hq_position = None
        self.session_dir = None
        self.turns_path = None
        self.logs_path = None


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
    inactive_arena_ticks = 0
    missing_hq_ticks = 0

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
            inactive_arena_ticks += 1
            if active_round and session_writer.turns_path is not None:
                logging.info(
                    "arena inactive tick=%s/%s — waiting before finishing round",
                    inactive_arena_ticks,
                    ARENA_INACTIVE_GRACE_TICKS,
                )
                append_jsonl(
                    session_writer.turns_path,
                    {
                        "capturedAt": utc_now(),
                        "kind": "arena_inactive",
                        "ticks": inactive_arena_ticks,
                    },
                )
            if inactive_arena_ticks < ARENA_INACTIVE_GRACE_TICKS:
                await _sleep_remaining(tick_started, poll_interval)
                continue
            if active_round and session_writer.turns_path is not None:
                append_jsonl(
                    session_writer.turns_path,
                    {
                        "capturedAt": utc_now(),
                        "kind": "round_finished",
                        "lastTurnNo": last_submitted_turn,
                        "reason": "arena_inactive",
                    },
                )
                logging.info("round finished (last turn %s)", last_submitted_turn)
            active_round = False
            last_submitted_turn = None
            inactive_arena_ticks = 0
            missing_hq_ticks = 0
            session_writer.close_round()
            await _sleep_remaining(tick_started, poll_interval)
            continue
        inactive_arena_ticks = 0

        hq_id = find_hq_id(arena)
        hq_position = find_hq_position(arena)
        if hq_id is None:
            missing_hq_ticks += 1
            logging.info(
                "turn=%s nextTurnIn=%.3f no HQ plantation tick=%s/%s — waiting",
                arena.turn_no,
                arena.next_turn_in,
                missing_hq_ticks,
                HQ_MISSING_GRACE_TICKS,
            )
            if active_round and session_writer.turns_path is not None:
                append_jsonl(
                    session_writer.turns_path,
                    {
                        "capturedAt": utc_now(),
                        "kind": "hq_missing",
                        "turnNo": arena.turn_no,
                        "nextTurnIn": arena.next_turn_in,
                        "ticks": missing_hq_ticks,
                    },
                )
            if active_round and missing_hq_ticks >= HQ_MISSING_GRACE_TICKS:
                if session_writer.turns_path is not None:
                    append_jsonl(
                        session_writer.turns_path,
                        {
                            "capturedAt": utc_now(),
                            "kind": "round_finished",
                            "lastTurnNo": last_submitted_turn,
                            "reason": "hq_missing",
                        },
                    )
                logging.info("round finished after HQ missing for %s ticks", missing_hq_ticks)
                active_round = False
                last_submitted_turn = None
                session_writer.close_round()
            await _sleep_remaining(tick_started, poll_interval)
            continue
        missing_hq_ticks = 0

        if not active_round:
            opened = session_writer.open_round(hq_id, hq_position)
            if not opened:
                logging.warning("active round has no session dir for hqId=%s", hq_id)
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
        else:
            previous_hq_position = session_writer.current_hq_position
            if (
                previous_hq_position is not None
                and hq_position is not None
                and not is_relocate_position(previous_hq_position, hq_position)
            ):
                if session_writer.turns_path is not None:
                    append_jsonl(
                        session_writer.turns_path,
                        {
                            "capturedAt": utc_now(),
                            "kind": "round_finished",
                            "lastTurnNo": last_submitted_turn,
                            "reason": "hq_jump",
                            "previousHqPosition": previous_hq_position,
                            "hqPosition": hq_position,
                            "turnNo": arena.turn_no,
                        },
                    )
                logging.info(
                    "hq jumped: %s -> %s, starting new session",
                    previous_hq_position,
                    hq_position,
                )
                active_round = False
                last_submitted_turn = None
                session_writer.close_round()
                opened = session_writer.open_round(hq_id, hq_position)
                if not opened:
                    logging.warning("failed to open new session after HQ jump for hqId=%s", hq_id)
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
                        "reason": "hq_jump",
                    },
                )
                active_round = True
            id_changed, position_changed, previous_hq_id, previous_hq_position = session_writer.note_hq(
                hq_id,
                hq_position,
            )
            if position_changed and previous_hq_position is not None and session_writer.turns_path is not None:
                logging.info(
                    "hq relocated: %s -> %s within session dir=%s",
                    previous_hq_position,
                    hq_position,
                    session_writer.session_dir,
                )
                append_jsonl(
                    session_writer.turns_path,
                    {
                        "capturedAt": utc_now(),
                        "kind": "hq_relocated",
                        "previousHqId": previous_hq_id,
                        "hqId": hq_id,
                        "previousHqPosition": previous_hq_position,
                        "hqPosition": hq_position,
                        "turnNo": arena.turn_no,
                        "arena": serialize(arena),
                    },
                )
            elif id_changed and session_writer.turns_path is not None:
                logging.info(
                    "hq identity changed: %s -> %s within session dir=%s",
                    previous_hq_id,
                    hq_id,
                    session_writer.session_dir,
                )
                append_jsonl(
                    session_writer.turns_path,
                    {
                        "capturedAt": utc_now(),
                        "kind": "hq_identity_changed",
                        "previousHqId": previous_hq_id,
                        "hqId": hq_id,
                        "turnNo": arena.turn_no,
                        "arena": serialize(arena),
                    },
                )

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
