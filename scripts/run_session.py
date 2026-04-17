#!/usr/bin/env python3
"""Record arena snapshots and logs across active rounds."""

from __future__ import annotations

import argparse
import json
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
from cherviak.strategies import MvpStrategy, PassiveStrategy


DEFAULT_OUTPUT_DIR = Path("artifacts/sessions")
STRATEGIES = {
    PassiveStrategy.name: PassiveStrategy,
    MvpStrategy.name: MvpStrategy,
}


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


def main() -> int:
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

    last_turn_no: int | None = None
    last_logs_poll = 0.0
    seen_log_keys: set[tuple[str, str]] = set()
    active_round = False

    with GameClient(config) as client:
        while True:
            now = time.monotonic()
            try:
                arena = client.get_arena()
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
                active_round = False
                time.sleep(args.idle_sleep)
                continue
            except httpx.HTTPError as exc:
                append_jsonl(
                    turns_path,
                    {
                        "capturedAt": utc_now(),
                        "kind": "network_error",
                        "error": str(exc),
                    },
                )
                time.sleep(args.idle_sleep)
                continue

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
                last_turn_no = None
                time.sleep(args.idle_sleep)
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

            if arena.turn_no != last_turn_no:
                command = strategy.decide_turn(arena)
                response = None
                if args.submit and command:
                    try:
                        response = client.post_command(command)
                    except httpx.HTTPError as exc:
                        response = {"error": str(exc)}

                strategy.on_turn_result(arena, command, response)
                append_jsonl(
                    turns_path,
                    {
                        "capturedAt": utc_now(),
                        "kind": "turn",
                        "turnNo": arena.turn_no,
                        "nextTurnIn": arena.next_turn_in,
                        "arena": serialize(arena),
                        "decision": command,
                        "response": response,
                    },
                )
                print(
                    f"turn={arena.turn_no} plantations={len(arena.plantations)} "
                    f"cells={len(arena.cells)} command={'yes' if command else 'no'}"
                )
                last_turn_no = arena.turn_no

            if now - last_logs_poll >= args.logs_interval:
                try:
                    logs = client.get_logs()
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
                last_logs_poll = now

            sleep_for = min(max(arena.next_turn_in, 0.1), 1.0)
            time.sleep(sleep_for)


if __name__ == "__main__":
    raise SystemExit(main())
