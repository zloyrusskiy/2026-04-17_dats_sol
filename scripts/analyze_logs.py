#!/usr/bin/env python3
"""Fetch and analyze DatsSol player logs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


DEFAULT_BASE_URL = "https://games-test.datsteam.dev"
DEFAULT_OUTPUT_DIR = Path("artifacts/logs")


@dataclass(frozen=True)
class EventRule:
    name: str
    severity: str
    patterns: tuple[re.Pattern[str], ...]


EVENT_RULES = (
    EventRule(
        "hq_spawn",
        "info",
        (
            re.compile(r"\bspawn\w*.*\b(main|hq)\b", re.IGNORECASE),
            re.compile(r"\b(main|hq)\b.*\bspawn\w*", re.IGNORECASE),
            re.compile(r"\b(цу|главн\w+ плантац\w*)\b.*\b(появ|создан|заспавн)", re.IGNORECASE),
        ),
    ),
    EventRule(
        "hq_destroyed",
        "critical",
        (
            re.compile(r"\b(main|hq)\b.*\b(destroyed|killed|lost|dead)", re.IGNORECASE),
            re.compile(r"\b(цу|главн\w+ плантац\w*)\b.*\b(уничтож|разруш|потерян)", re.IGNORECASE),
        ),
    ),
    EventRule(
        "plantation_destroyed",
        "critical",
        (
            re.compile(r"\bplantation\b.*\b(destroyed|killed|lost|dead)", re.IGNORECASE),
            re.compile(r"\bплантац\w*\b.*\b(уничтож|разруш|потерян)", re.IGNORECASE),
        ),
    ),
    EventRule(
        "respawn",
        "info",
        (
            re.compile(r"\brespawn\w*", re.IGNORECASE),
            re.compile(r"\bвозрож", re.IGNORECASE),
            re.compile(r"\bреспавн", re.IGNORECASE),
        ),
    ),
    EventRule(
        "upgrade",
        "info",
        (
            re.compile(r"\bupgrade\b", re.IGNORECASE),
            re.compile(r"\bулучшен", re.IGNORECASE),
            re.compile(r"\bапгрейд", re.IGNORECASE),
        ),
    ),
    EventRule(
        "earthquake",
        "warning",
        (
            re.compile(r"\bearthquake\b", re.IGNORECASE),
            re.compile(r"\bземлетряс", re.IGNORECASE),
        ),
    ),
    EventRule(
        "sandstorm",
        "warning",
        (
            re.compile(r"\bsandstorm\b", re.IGNORECASE),
            re.compile(r"\bбур", re.IGNORECASE),
        ),
    ),
    EventRule(
        "beaver",
        "warning",
        (
            re.compile(r"\bbeaver\b", re.IGNORECASE),
            re.compile(r"\bбобр", re.IGNORECASE),
        ),
    ),
    EventRule(
        "repair",
        "info",
        (
            re.compile(r"\brepair\w*", re.IGNORECASE),
            re.compile(r"\bремонт", re.IGNORECASE),
        ),
    ),
    EventRule(
        "build",
        "info",
        (
            re.compile(r"\b(build|constructed|construction)\b", re.IGNORECASE),
            re.compile(r"\b(стройк|постро)\b", re.IGNORECASE),
        ),
    ),
    EventRule(
        "attack_or_sabotage",
        "warning",
        (
            re.compile(r"\b(attack|sabotage|damage|damaged)\b", re.IGNORECASE),
            re.compile(r"\b(атак|диверс|урон)\b", re.IGNORECASE),
        ),
    ),
)

UPGRADE_NAME_RE = re.compile(
    r"\b(repair_power|max_hp|settlement_limit|signal_range|vision_range|"
    r"decay_mitigation|earthquake_mitigation|beaver_damage_mitigation)\b"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Получить и осмысленно разобрать логи DatsSol."
    )
    parser.add_argument(
        "--input-json",
        type=Path,
        help="Локальный JSON-массив логов. Если указан, API не вызывается.",
    )
    parser.add_argument(
        "--token",
        help="Токен API. По умолчанию берётся из DATS_TOKEN или TOKEN.",
    )
    parser.add_argument(
        "--base-url",
        help=f"Базовый URL API. По умолчанию {DEFAULT_BASE_URL}.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Куда сохранить сырые логи. По умолчанию {DEFAULT_OUTPUT_DIR}.",
    )
    parser.add_argument(
        "--save-raw",
        action="store_true",
        help="Сохранить сырой ответ logs в output-dir.",
    )
    parser.add_argument(
        "--recent",
        type=int,
        default=12,
        help="Сколько последних важных событий показать.",
    )
    return parser.parse_args()


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def get_token(cli_token: str | None) -> str:
    token = cli_token or os.getenv("DATS_TOKEN") or os.getenv("TOKEN")
    if not token:
        raise SystemExit(
            "Не найден API токен. Укажи --token или добавь DATS_TOKEN в .env."
        )
    return token


def get_base_url(cli_base_url: str | None) -> str:
    return (
        cli_base_url
        or os.getenv("DATS_BASE_URL")
        or os.getenv("BASE_URL")
        or DEFAULT_BASE_URL
    ).rstrip("/")


def fetch_logs(base_url: str, token: str) -> list[dict[str, Any]]:
    with httpx.Client(
        base_url=base_url,
        headers={
            "X-Auth-Token": token,
            "Accept": "application/json",
            "User-Agent": "dats-sol-log-analyzer/1.0",
        },
        timeout=10.0,
    ) as client:
        response = client.get("/api/logs")
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, list):
        raise SystemExit(f"Ожидался массив логов, пришло: {payload!r}")
    return payload


def save_logs(logs: list[dict[str, Any]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"player_logs_{timestamp}.json"
    output_path.write_text(
        json.dumps(logs, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def normalize_message(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def classify_message(message: str) -> list[tuple[str, str]]:
    matched: list[tuple[str, str]] = []
    for rule in EVENT_RULES:
        if any(pattern.search(message) for pattern in rule.patterns):
            matched.append((rule.name, rule.severity))
    return matched or [("other", "info")]


def extract_upgrade_name(message: str) -> str | None:
    match = UPGRADE_NAME_RE.search(message)
    return match.group(1) if match else None


def severity_rank(value: str) -> int:
    return {"critical": 0, "warning": 1, "info": 2}.get(value, 3)


def analyze_logs(logs: list[dict[str, Any]]) -> dict[str, Any]:
    type_counter: Counter[str] = Counter()
    severity_counter: Counter[str] = Counter()
    upgrades: Counter[str] = Counter()
    important_events: list[dict[str, Any]] = []
    hq_status = "unknown"
    hq_status_event: dict[str, Any] | None = None

    parsed_entries: list[dict[str, Any]] = []
    for raw_entry in logs:
        message = normalize_message(raw_entry.get("message"))
        entry = {
            "time": raw_entry.get("time"),
            "parsed_time": parse_time(raw_entry.get("time")),
            "message": message,
        }
        parsed_entries.append(entry)

    parsed_entries.sort(
        key=lambda item: (
            item["parsed_time"] is None,
            item["parsed_time"] or datetime.min,
            item["message"],
        )
    )

    for entry in parsed_entries:
        matches = classify_message(entry["message"])
        event_names = [name for name, _ in matches]
        severity = min((sev for _, sev in matches), key=severity_rank)

        for event_name in event_names:
            type_counter[event_name] += 1
        severity_counter[severity] += 1

        if "upgrade" in event_names:
            upgrade_name = extract_upgrade_name(entry["message"])
            if upgrade_name:
                upgrades[upgrade_name] += 1

        if "hq_spawn" in event_names or "respawn" in event_names:
            hq_status = "active"
            hq_status_event = entry
        if "hq_destroyed" in event_names:
            hq_status = "destroyed"
            hq_status_event = entry

        if severity in {"critical", "warning"} or "upgrade" in event_names:
            important_events.append(
                {
                    "time": entry["time"],
                    "severity": severity,
                    "events": event_names,
                    "message": entry["message"],
                }
            )

    oldest = parsed_entries[0]["time"] if parsed_entries else None
    newest = parsed_entries[-1]["time"] if parsed_entries else None
    return {
        "total": len(parsed_entries),
        "oldest_time": oldest,
        "newest_time": newest,
        "type_counter": type_counter,
        "severity_counter": severity_counter,
        "upgrades": upgrades,
        "important_events": important_events,
        "hq_status": hq_status,
        "hq_status_event": hq_status_event,
    }


def render_summary(analysis: dict[str, Any], recent: int) -> str:
    lines: list[str] = []
    lines.append("DatsSol logs analysis")
    lines.append("")
    lines.append(f"Всего записей: {analysis['total']}")
    if analysis["oldest_time"] or analysis["newest_time"]:
        lines.append(
            f"Диапазон: {analysis['oldest_time'] or '?'} .. {analysis['newest_time'] or '?'}"
        )

    lines.append("")
    lines.append("Сводка по типам событий:")
    for name, count in analysis["type_counter"].most_common():
        lines.append(f"- {name}: {count}")

    lines.append("")
    hq_status = analysis["hq_status"]
    if hq_status == "active":
        lines.append("Состояние ЦУ: по логам выглядит живым/перерождённым.")
    elif hq_status == "destroyed":
        lines.append("Состояние ЦУ: последнее связанное событие говорит, что ЦУ уничтожен.")
    else:
        lines.append("Состояние ЦУ: по логам не удалось надёжно определить.")

    if analysis["hq_status_event"]:
        event = analysis["hq_status_event"]
        lines.append(f"Последнее событие ЦУ: {event['time'] or '?'} | {event['message']}")

    if analysis["upgrades"]:
        lines.append("")
        lines.append("Апгрейды из логов:")
        for name, count in analysis["upgrades"].most_common():
            lines.append(f"- {name}: {count}")

    lines.append("")
    lines.append(f"Последние важные события ({min(recent, len(analysis['important_events']))}):")
    if not analysis["important_events"]:
        lines.append("- Нет warning/critical событий и сообщений про апгрейды.")
    else:
        for event in analysis["important_events"][-recent:]:
            labels = ",".join(event["events"])
            lines.append(
                f"- [{event['severity']}] {event['time'] or '?'} | {labels} | {event['message']}"
            )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    load_dotenv(Path(".env"))

    if args.input_json:
        logs = json.loads(args.input_json.read_text(encoding="utf-8"))
        if not isinstance(logs, list):
            raise SystemExit("Файл --input-json должен содержать JSON-массив логов.")
    else:
        token = get_token(args.token)
        base_url = get_base_url(args.base_url)
        try:
            logs = fetch_logs(base_url, token)
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            raise SystemExit(f"Ошибка API: HTTP {exc.response.status_code}\n{body}") from exc
        except httpx.HTTPError as exc:
            raise SystemExit(f"Не удалось подключиться к API: {exc}") from exc

    if args.save_raw:
        output_path = save_logs(logs, args.output_dir)
        print(f"Raw logs saved to: {output_path}")
        print("")

    print(render_summary(analyze_logs(logs), args.recent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
