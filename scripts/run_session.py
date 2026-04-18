#!/usr/bin/env python3
"""Record arena snapshots and logs across active rounds."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from cherviak.client import GameClient
from cherviak.config import load_config
from cherviak.strategies import LateralStrategy, PassiveStrategy


DEFAULT_OUTPUT_DIR = Path("artifacts/sessions")
STRATEGIES = {
    PassiveStrategy.name: PassiveStrategy,
    LateralStrategy.name: LateralStrategy,
}

# Floor for the sleep between arena polls to avoid a busy loop when the
# server-reported boundary is effectively "now".
MIN_POLL_SLEEP = 0.02
LATENCY_ALPHA = 0.2
LATENCY_JITTER_ALPHA = 0.2
ARENA_WARMUP_SAMPLES = 3
TURN_BOUNDARY_MARGIN = 0.03


def available_strategy_names() -> list[str]:
    return sorted(STRATEGIES)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Запустить recorder и писать arena/logs в историю."
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
        help="Как часто запрашивать /api/logs во время активной игры.",
    )
    parser.add_argument(
        "--idle-sleep",
        type=float,
        default=5.0,
        help="Пауза между проверками, когда активной игры нет.",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Разрешить отправку команд стратегии. По умолчанию recorder только пишет историю.",
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


def make_session_dir(root: Path) -> Path:
    session_dir = root / datetime.now(timezone.utc).strftime("session_%Y%m%dT%H%M%SZ")
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def write_meta(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compute_retry_after_seconds(exc: httpx.HTTPStatusError, default: float) -> float:
    retry_after = exc.response.headers.get("Retry-After", "").strip()
    try:
        retry_after_seconds = float(retry_after)
    except ValueError:
        retry_after_seconds = 0.0
    return max(default, retry_after_seconds)


def compute_logs_backoff_seconds(exc: httpx.HTTPStatusError, default: float) -> float:
    return compute_retry_after_seconds(exc, default)


def update_latency_estimate(
    state: dict[str, float],
    observed_latency: float,
) -> tuple[float, float]:
    """Update one-way latency EWMA and jitter EWMA; return both."""
    if not state:
        state["mean"] = observed_latency
        state["jitter"] = 0.0
        return state["mean"], state["jitter"]

    previous_mean = state["mean"]
    mean = (1.0 - LATENCY_ALPHA) * previous_mean + LATENCY_ALPHA * observed_latency
    jitter = (
        (1.0 - LATENCY_JITTER_ALPHA) * state["jitter"]
        + LATENCY_JITTER_ALPHA * abs(observed_latency - previous_mean)
    )
    state["mean"] = mean
    state["jitter"] = jitter
    return mean, jitter


def effective_latency(mean_latency: float, jitter: float) -> float:
    """Conservative one-way estimate used for deadline checks."""
    return mean_latency + 2.0 * jitter


def warmup_complete(sample_count: int) -> bool:
    return sample_count >= ARENA_WARMUP_SAMPLES


def compute_arena_sleep(next_turn_in: float, latency: float) -> float:
    return max(MIN_POLL_SLEEP, next_turn_in - latency / 2.0 - TURN_BOUNDARY_MARGIN)


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
    if response.get("skipped"):
        return str(response["skipped"])
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


async def fetch_arena(client: GameClient) -> tuple[Any, float]:
    """GET /api/arena; return (arena, rtt)."""
    t_send = time.monotonic()
    arena = await asyncio.to_thread(client.get_arena)
    return arena, time.monotonic() - t_send


async def safe_fetch_arena(
    client: GameClient,
    turns_path: Path,
    idle_sleep: float,
) -> tuple[Any, float]:
    """Fetch arena with automatic backoff on transport/HTTP errors."""
    while True:
        try:
            return await fetch_arena(client)
        except httpx.HTTPStatusError as exc:
            append_jsonl(
                turns_path,
                {
                    "capturedAt": utc_now(),
                    "kind": "http_error",
                    "statusCode": exc.response.status_code,
                    "body": exc.response.text,
                },
            )
        except httpx.HTTPError as exc:
            append_jsonl(
                turns_path,
                {
                    "capturedAt": utc_now(),
                    "kind": "network_error",
                    "error": str(exc),
                },
            )
        await asyncio.sleep(idle_sleep)


async def decide_and_submit(
    strategy: Any,
    client: GameClient,
    arena: Any,
    args: argparse.Namespace,
    turns_path: Path,
    command_state: dict[str, float],
) -> None:
    """Compute the strategy's decision and POST the command.

    Runs as a background task so the main loop can proceed to its
    next-arena sleep immediately.
    """
    decision_started_at = time.perf_counter()
    command = strategy.decide_turn(arena)
    decision_elapsed_ms = (time.perf_counter() - decision_started_at) * 1000

    response: dict[str, Any] | None = None
    if args.submit and command:
        submit_now = time.monotonic()
        if submit_now < command_state["backoff_until"]:
            response = {
                "skipped": "rate_limit_backoff",
                "retryInSeconds": round(command_state["backoff_until"] - submit_now, 3),
            }
        else:
            try:
                response = await asyncio.to_thread(client.post_command, command)
                command_state["backoff_until"] = 0.0
            except httpx.HTTPStatusError as exc:
                response = {
                    "error": str(exc),
                    "statusCode": exc.response.status_code,
                    "body": exc.response.text,
                }
                if exc.response.status_code == 429:
                    backoff_seconds = compute_retry_after_seconds(exc, default=1.0)
                    command_state["backoff_until"] = time.monotonic() + backoff_seconds
                    response["retryInSeconds"] = backoff_seconds
                    logging.warning(
                        "turn=%s command rate-limited; backoff %.2f s",
                        arena.turn_no,
                        backoff_seconds,
                    )
            except httpx.HTTPError as exc:
                response = {"error": str(exc)}

    strategy.on_turn_result(arena, command, response)
    command_status = describe_command_status(command, args.submit, response)
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
            "arena": serialize(arena),
            "decision": command,
            "response": response,
        },
    )
    logging.info(
        "turn=%s decision_time_ms=%.1f plantations=%s cells=%s construction=%s decision=%s command=%s errors=%s",
        arena.turn_no,
        decision_elapsed_ms,
        len(arena.plantations),
        len(arena.cells),
        construction_status,
        decision_summary,
        command_status,
        response_errors,
    )


async def logs_loop(
    config: Any,
    logs_path: Path,
    interval: float,
    stop_event: asyncio.Event,
) -> None:
    """Standalone coroutine polling /api/logs independently of game ticks."""
    seen_log_keys: set[tuple[str, str]] = set()
    backoff_until = 0.0
    with GameClient(config, log_requests=False) as client:
        while not stop_event.is_set():
            now = time.monotonic()
            if now < backoff_until:
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=min(backoff_until - now, 1.0),
                    )
                    return
                except asyncio.TimeoutError:
                    continue

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
                if exc.response.status_code == 429:
                    backoff_until = time.monotonic() + compute_logs_backoff_seconds(
                        exc, default=max(interval, 5.0)
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
    args: argparse.Namespace,
    turns_path: Path,
) -> None:
    """Main game cycle.

    Steps per tick:
      1. Seed arena (first iteration) or refresh it.
      2. latency := rtt / 2.
      3. If next_turn_in < 2*latency → warn, skip command (can't deliver in time).
      4. Else spawn decide+submit as a background task (does not block the loop).
      5. Sleep (next_turn_in - latency / 2 - boundary_margin), then loop.
    """
    last_turn_no: int | None = None
    active_round = False
    active_round_samples = 0
    command_state: dict[str, float] = {"backoff_until": 0.0}
    decision_task: asyncio.Task | None = None
    latency_state: dict[str, float] = {}

    arena, rtt = await safe_fetch_arena(client, turns_path, args.idle_sleep)

    while True:
        observed_latency = rtt / 2.0
        mean_latency, jitter = update_latency_estimate(latency_state, observed_latency)
        latency = effective_latency(mean_latency, jitter)

        if not looks_like_active_arena(arena):
            if active_round:
                append_jsonl(
                    turns_path,
                    {
                        "capturedAt": utc_now(),
                        "kind": "round_finished",
                        "lastTurnNo": last_turn_no,
                    },
                )
            active_round = False
            active_round_samples = 0
            last_turn_no = None
            await asyncio.sleep(args.idle_sleep)
            arena, rtt = await safe_fetch_arena(client, turns_path, args.idle_sleep)
            continue

        if not active_round:
            strategy.on_round_started()
            append_jsonl(
                turns_path,
                {
                    "capturedAt": utc_now(),
                    "kind": "round_started",
                    "turnNo": arena.turn_no,
                    "arena": serialize(arena),
                },
            )
            active_round = True
            active_round_samples = 1
        else:
            active_round_samples += 1

        if not warmup_complete(active_round_samples):
            logging.info(
                "turn=%s arena warmup sample %s/%s — delaying commands",
                arena.turn_no,
                active_round_samples,
                ARENA_WARMUP_SAMPLES,
            )
        elif arena.turn_no != last_turn_no:
            if arena.next_turn_in < 2 * latency:
                logging.warning(
                    "turn=%s nextTurnIn=%.3f < 2*latency=%.3f (observed=%.3f mean=%.3f jitter=%.3f) — skipping submit (won't reach server in time)",
                    arena.turn_no,
                    arena.next_turn_in,
                    2 * latency,
                    observed_latency,
                    mean_latency,
                    jitter,
                )
            elif decision_task is not None and not decision_task.done():
                logging.warning(
                    "turn=%s previous decision still running — skipping submit",
                    arena.turn_no,
                )
            else:
                decision_task = asyncio.create_task(
                    decide_and_submit(
                        strategy, client, arena, args, turns_path, command_state
                    )
                )
            last_turn_no = arena.turn_no

        sleep_for = compute_arena_sleep(arena.next_turn_in, latency)
        await asyncio.sleep(sleep_for)
        arena, rtt = await safe_fetch_arena(client, turns_path, args.idle_sleep)


async def main_async() -> int:
    configure_logging()
    args = parse_args()
    config = load_config()
    strategy = STRATEGIES[args.strategy]()

    session_dir = make_session_dir(args.output_dir)
    meta_path = session_dir / "meta.json"
    turns_path = session_dir / "turns.jsonl"
    logs_path = session_dir / "logs.jsonl"

    write_meta(
        meta_path,
        {
            "startedAt": utc_now(),
            "baseUrl": config.base_url,
            "strategy": strategy.name,
            "submit": args.submit,
            "logsInterval": args.logs_interval,
            "idleSleep": args.idle_sleep,
        },
    )

    print(f"Session dir: {session_dir}")

    stop_event = asyncio.Event()
    logs_task = asyncio.create_task(
        logs_loop(config, logs_path, args.logs_interval, stop_event)
    )

    try:
        with GameClient(config, log_requests=True) as client:
            await play_loop(client, strategy, args, turns_path)
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
