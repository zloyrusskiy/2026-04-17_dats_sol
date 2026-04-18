#!/usr/bin/env python3
"""Serve a local web UI for browsing recorded DatsSol sessions."""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_SESSIONS_DIR = Path("artifacts/sessions")


TURN_IN_MESSAGE_RE = re.compile(r"\[Turn (\d+)\]")
SPAWN_PLANTATION_RE = re.compile(
    r"Spawned (?:(MAIN) )?plantation at \[(\d+)\s+(\d+)\](?: \(HP=(\d+)\))?",
    re.IGNORECASE,
)
LEGEND_ITEMS = [
    {"color": "#fff7d6", "label": "bonus cell"},
    {"color": "#7b8794", "label": "mountain"},
    {"color": "#9fb3ff", "label": "construction"},
    {"color": "#0e9f6e", "label": "your plantation"},
    {"color": "#98a2b3", "label": "isolated plantation"},
    {"color": "#f0b429", "label": "your HQ"},
    {"color": "#d64545", "label": "enemy plantation"},
    {"color": "#8d6e63", "label": "beaver"},
    {"color": "#8d2b0b", "label": "spawn highlight"},
]


@dataclass(frozen=True)
class AppConfig:
    sessions_dir: Path
    cell_size: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Поднять локальный web viewer для игровых сессий DatsSol."
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Хост для HTTP-сервера. По умолчанию {DEFAULT_HOST}.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Порт для HTTP-сервера. По умолчанию {DEFAULT_PORT}.",
    )
    parser.add_argument(
        "--sessions-dir",
        type=Path,
        default=DEFAULT_SESSIONS_DIR,
        help=f"Каталог с записями сессий. По умолчанию {DEFAULT_SESSIONS_DIR}.",
    )
    parser.add_argument(
        "--cell-size",
        type=int,
        default=18,
        help="Размер клетки в SVG-визуализации.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def session_dir_created_ts(session_path: Path) -> float:
    stat = session_path.stat()
    return getattr(stat, "st_birthtime", stat.st_mtime)


def isoformat_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def summarize_session(session_path: Path) -> dict[str, Any]:
    meta_path = session_path / "meta.json"
    turns_path = session_path / "turns.jsonl"
    logs_path = session_path / "logs.jsonl"

    meta = load_json(meta_path) if meta_path.exists() else {}
    frame_count = 0
    first_turn: int | None = None
    last_turn: int | None = None

    with turns_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("kind") != "turn":
                continue
            turn_no = row.get("turnNo")
            if not isinstance(turn_no, int):
                continue
            frame_count += 1
            if first_turn is None:
                first_turn = turn_no
            last_turn = turn_no

    log_count = 0
    if logs_path.exists():
        with logs_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                if raw_line.strip():
                    log_count += 1
    created_ts = session_dir_created_ts(session_path)

    return {
        "id": session_path.name,
        "label": session_path.name,
        "createdAt": isoformat_utc(created_ts),
        "createdTs": created_ts,
        "startedAt": meta.get("startedAt"),
        "strategy": meta.get("strategy"),
        "hqId": meta.get("hqId"),
        "latencyAvg": meta.get("latencyAvg"),
        "frameCount": frame_count,
        "logCount": log_count,
        "firstTurn": first_turn,
        "lastTurn": last_turn,
    }


def extract_turn_from_log(entry: dict[str, Any]) -> int | None:
    message = str(entry.get("message", ""))
    match = TURN_IN_MESSAGE_RE.search(message)
    if match:
        return int(match.group(1))
    return None


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def progress_color(progress: int) -> str:
    ratio = clamp(progress / 100.0, 0.0, 1.0)
    red = int(225 - ratio * 120)
    green = int(235 - ratio * 35)
    blue = int(225 - ratio * 145)
    return f"rgb({red},{green},{blue})"


def format_attrs(attrs: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in attrs.items():
        if value is None:
            continue
        normalized_key = key[:-1] if key.endswith("_") else key
        normalized_key = normalized_key.replace("_", "-")
        escaped = str(value).replace('"', "&quot;")
        parts.append(f' {normalized_key}="{escaped}"')
    return "".join(parts)


def svg_rect(x: float, y: float, width: float, height: float, **attrs: Any) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}"'
        f'{format_attrs(attrs)} />'
    )


def svg_circle(cx: float, cy: float, r: float, **attrs: Any) -> str:
    return f'<circle cx="{cx}" cy="{cy}" r="{r}"{format_attrs(attrs)} />'


def svg_text(x: float, y: float, text: str, **attrs: Any) -> str:
    return f'<text x="{x}" y="{y}"{format_attrs(attrs)}>{escape(text)}</text>'


def svg_polygon(points: list[tuple[float, float]], **attrs: Any) -> str:
    points_text = " ".join(f"{x},{y}" for x, y in points)
    return f'<polygon points="{points_text}"{format_attrs(attrs)} />'


def parse_spawn_event(message: str) -> dict[str, Any] | None:
    match = SPAWN_PLANTATION_RE.search(message)
    if not match:
        return None
    is_main, x, y, hp = match.groups()
    return {
        "kind": "spawn",
        "position": [int(x), int(y)],
        "isMain": bool(is_main),
        "hp": None if hp is None else int(hp),
    }


def render_svg(arena: dict[str, Any], cell_size: int, overlays: list[dict[str, Any]] | None = None) -> str:
    width, height = arena["size"]
    margin = 42
    map_width = width * cell_size
    map_height = height * cell_size
    canvas_width = map_width + margin * 2
    canvas_height = max(map_height + margin * 2, 420)

    def cell_origin(x: int, y: int) -> tuple[int, int]:
        return margin + x * cell_size, margin + y * cell_size

    def cell_center(x: int, y: int) -> tuple[float, float]:
        ox, oy = cell_origin(x, y)
        return ox + cell_size / 2, oy + cell_size / 2

    svg: list[str] = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width}" '
            f'height="{canvas_height}" viewBox="0 0 {canvas_width} {canvas_height}" '
            f'data-grid-width="{width}" data-grid-height="{height}" '
            f'data-cell-size="{cell_size}" data-grid-margin="{margin}">'
        ),
        "<style>",
        "text { font-family: 'SFMono-Regular', 'Menlo', monospace; }",
        ".small { font-size: 11px; fill: #52606d; }",
        ".label { font-size: 12px; fill: #102a43; }",
        ".title { font-size: 20px; font-weight: bold; fill: #102a43; }",
        "</style>",
        svg_rect(0, 0, canvas_width, canvas_height, fill="#f4f7fb"),
        svg_rect(margin, margin, map_width, map_height, fill="#ffffff", stroke="#bcccdc"),
    ]

    if width and height:
        for x in range(width + 1):
            xpos = margin + x * cell_size
            svg.append(
                f'<line x1="{xpos}" y1="{margin}" x2="{xpos}" y2="{margin + map_height}" '
                'stroke="#e4e7eb" stroke-width="1" />'
            )
        for y in range(height + 1):
            ypos = margin + y * cell_size
            svg.append(
                f'<line x1="{margin}" y1="{ypos}" x2="{margin + map_width}" y2="{ypos}" '
                'stroke="#e4e7eb" stroke-width="1" />'
            )

    for y in range(height):
        for x in range(width):
            if x % 7 == 0 and y % 7 == 0:
                ox, oy = cell_origin(x, y)
                svg.append(svg_rect(ox + 1, oy + 1, cell_size - 2, cell_size - 2, fill="#fff7d6"))

    for mountain in arena.get("mountains", []):
        x, y = mountain
        ox, oy = cell_origin(x, y)
        svg.append(
            svg_rect(
                ox + 1,
                oy + 1,
                cell_size - 2,
                cell_size - 2,
                fill="#7b8794",
                stroke="#52606d",
                stroke_width="1",
            )
        )
        cx, cy = cell_center(x, y)
        svg.append(svg_text(cx, cy + 4, "M", class_="label", fill="#ffffff", text_anchor="middle"))

    for cell in arena.get("cells", []):
        x, y = cell["position"]
        ox, oy = cell_origin(x, y)
        svg.append(
            svg_rect(
                ox + 2,
                oy + 2,
                cell_size - 4,
                cell_size - 4,
                fill=progress_color(cell["terraformationProgress"]),
                stroke="#486581" if x % 7 == 0 and y % 7 == 0 else "#9fb3c8",
                stroke_width="1",
            )
        )

    for construction in arena.get("construction", []):
        x, y = construction["position"]
        ox, oy = cell_origin(x, y)
        svg.append(
            svg_rect(
                ox + 4,
                oy + 4,
                cell_size - 8,
                cell_size - 8,
                fill="#9fb3ff",
                stroke="#3e4c59",
                stroke_dasharray="4 2",
            )
        )
        cx, cy = cell_center(x, y)
        svg.append(svg_text(cx, cy + 4, str(construction["progress"]), class_="small", text_anchor="middle"))

    for plantation in arena.get("enemy", []):
        x, y = plantation["position"]
        cx, cy = cell_center(x, y)
        r = cell_size * 0.34
        svg.append(
            svg_polygon(
                [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
                fill="#d64545",
                stroke="#7b1f1f",
                stroke_width="1.5",
            )
        )

    for plantation in arena.get("plantations", []):
        x, y = plantation["position"]
        cx, cy = cell_center(x, y)
        is_main = plantation.get("isMain", False)
        is_isolated = plantation.get("isIsolated", False)
        fill = "#0e9f6e" if not is_isolated else "#98a2b3"
        if is_main:
            outer = cell_size * 0.36
            inner = outer * 0.55
            points: list[tuple[float, float]] = []
            for index in range(8):
                angle = math.pi / 4 * index - math.pi / 2
                radius = outer if index % 2 == 0 else inner
                points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
            svg.append(
                svg_polygon(points, fill="#f0b429", stroke="#8d2b0b", stroke_width="1.5")
            )
        else:
            svg.append(
                svg_circle(
                    cx,
                    cy,
                    cell_size * 0.28,
                    fill=fill,
                    stroke="#1f2933",
                    stroke_width="1.5",
                )
            )

    for beaver in arena.get("beavers", []):
        x, y = beaver["position"]
        cx, cy = cell_center(x, y)
        svg.append(
            svg_circle(
                cx,
                cy,
                cell_size * 0.2,
                fill="#8d6e63",
                stroke="#5d4037",
                stroke_width="1.5",
            )
        )
        svg.append(svg_text(cx, cy + 4, "B", class_="small", fill="#ffffff", text_anchor="middle"))

    for overlay in overlays or []:
        position = overlay.get("position")
        if not isinstance(position, list) or len(position) != 2:
            continue
        x, y = position
        if not (0 <= x < width and 0 <= y < height):
            continue
        cx, cy = cell_center(x, y)
        ring_color = "#8d2b0b" if overlay.get("isMain") else "#0f766e"
        label = "NEW HQ" if overlay.get("isMain") else "NEW"
        svg.append(
            svg_circle(
                cx,
                cy,
                cell_size * 0.46,
                fill="none",
                stroke=ring_color,
                stroke_width="2.5",
                stroke_dasharray="5 3",
            )
        )
        svg.append(
            svg_circle(
                cx,
                cy,
                cell_size * 0.1,
                fill=ring_color,
                stroke="#fffaf2",
                stroke_width="1.5",
            )
        )
        svg.append(
            svg_text(
                cx,
                cy - cell_size * 0.56,
                label,
                class_="small",
                fill=ring_color,
                text_anchor="middle",
            )
        )

    svg.append("</svg>")
    return "\n".join(svg)


def build_legend(arena: dict[str, Any]) -> dict[str, Any]:
    width, height = arena["size"]
    return {
        "title": "DatsSol Session Frame",
        "stats": [
            f"turn: {arena.get('turnNo', '?')}",
            f"size: {width}x{height}",
            f"actionRange: {arena.get('actionRange', '?')}",
            f"plantations: {len(arena.get('plantations', []))}",
            f"cells: {len(arena.get('cells', []))}",
        ],
        "items": LEGEND_ITEMS,
    }


def build_logs_by_turn(log_rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    indexed: dict[tuple[int, int], list[dict[str, Any]]] = {}
    current_segment = 0
    previous_turn: int | None = None
    for row in log_rows:
        entry = row.get("entry")
        if not isinstance(entry, dict):
            continue
        turn_no = extract_turn_from_log(entry)
        if turn_no is None:
            continue
        if previous_turn is not None and turn_no < previous_turn:
            current_segment += 1
        previous_turn = turn_no
        indexed.setdefault((current_segment, turn_no), []).append(entry)
    return indexed


@lru_cache(maxsize=32)
def load_session(session_path_str: str, cell_size: int) -> dict[str, Any]:
    session_path = Path(session_path_str)
    meta = load_json(session_path / "meta.json") if (session_path / "meta.json").exists() else {}
    turn_rows = load_jsonl(session_path / "turns.jsonl")
    log_rows = load_jsonl(session_path / "logs.jsonl")
    logs_by_turn = build_logs_by_turn(log_rows)

    frames: list[dict[str, Any]] = []
    current_segment = 0
    previous_turn_no: int | None = None
    for row in turn_rows:
        if row.get("kind") != "turn":
            continue
        arena = row.get("arena")
        if not isinstance(arena, dict):
            continue
        turn_no = row.get("turnNo")
        if not isinstance(turn_no, int):
            continue
        if previous_turn_no is not None and turn_no < previous_turn_no:
            current_segment += 1
        previous_turn_no = turn_no
        frame_logs = logs_by_turn.get((current_segment, turn_no), [])
        overlays = [
            spawn_event
            for entry in frame_logs
            if (spawn_event := parse_spawn_event(str(entry.get("message", "")))) is not None
        ]
        plantation_count = len(arena.get("plantations", []))
        cell_count = len(arena.get("cells", []))
        hq = next((p for p in arena.get("plantations", []) if p.get("isMain")), None)
        frames.append(
            {
                "turnNo": turn_no,
                "capturedAt": row.get("capturedAt"),
                "nextTurnIn": row.get("nextTurnIn"),
                "plantations": plantation_count,
                "cells": cell_count,
                "hqHp": None if hq is None else hq.get("hp"),
                "hqId": None if hq is None else hq.get("id"),
                "hqPosition": None if hq is None else hq.get("position"),
                "strategyElapsedMs": row.get("strategyElapsedMs"),
                "submitElapsedMs": row.get("submitElapsedMs"),
                "svg": render_svg(arena, cell_size, overlays),
                "legend": build_legend(arena),
                "logs": frame_logs,
                "decision": row.get("decision"),
                "response": row.get("response"),
                "segment": current_segment,
            }
        )

    return {
        "id": session_path.name,
        "label": session_path.name,
        "path": str(session_path.resolve()),
        "meta": meta,
        "frames": frames,
        "logCount": len(log_rows),
    }


def list_sessions(sessions_dir: Path) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    if not sessions_dir.exists():
        return sessions

    for session_dir in sessions_dir.iterdir():
        if not session_dir.is_dir():
            continue
        if not (session_dir / "turns.jsonl").exists():
            continue
        sessions.append(summarize_session(session_dir.resolve()))
    sessions.sort(key=lambda session: (session["createdTs"], session["id"]), reverse=True)
    return sessions


def render_index_html() -> str:
    return """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>DatsSol Sessions</title>
  <style>
    :root {
      --bg: #f2ede3;
      --panel: rgba(255,250,240,0.94);
      --ink: #1f2933;
      --muted: #6b7280;
      --border: #d4c3ad;
      --accent: #9c4221;
      --accent-2: #0f766e;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Iosevka Aile", "Avenir Next", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, #fff9ed 0%, transparent 30%),
        linear-gradient(180deg, #f3ede2 0%, #e8dfcf 100%);
    }
    .app {
      height: 100vh;
      position: relative;
      padding: 14px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 18px;
      overflow: hidden;
      min-height: 0;
    }
    .sidebar {
      position: absolute;
      top: 14px;
      left: 14px;
      bottom: 14px;
      width: min(340px, calc(100vw - 28px));
      z-index: 10;
      display: flex;
      flex-direction: column;
      box-shadow: 0 18px 44px rgba(31, 41, 51, 0.18);
      transition: transform 180ms ease, box-shadow 180ms ease;
    }
    .app.sidebar-collapsed .sidebar {
      transform: translateX(calc(-100% - 14px));
      box-shadow: none;
    }
    .sidebar-header, .main-header {
      padding: 16px 18px;
      border-bottom: 1px solid var(--border);
      background: rgba(255,255,255,0.55);
    }
    .sidebar-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }
    .sidebar-header-copy {
      min-width: 0;
    }
    .title {
      margin: 0;
      font-size: 22px;
    }
    .subtitle {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 14px;
    }
    #sessionList {
      overflow: auto;
      padding: 10px;
      display: grid;
      gap: 10px;
    }
    .session-btn {
      width: 100%;
      text-align: left;
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px 14px;
      background: #fffdf8;
      cursor: pointer;
      font: inherit;
    }
    .session-btn.active {
      border-color: var(--accent);
      background: #fff2ea;
      box-shadow: inset 0 0 0 1px rgba(156,66,33,0.15);
    }
    .session-meta {
      margin-top: 6px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }
    .main {
      height: 100%;
      display: grid;
      grid-template-rows: auto auto 1fr auto;
      min-height: 0;
    }
    .main-header {
      display: flex;
      align-items: flex-start;
      gap: 12px;
    }
    .header-copy {
      min-width: 0;
    }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
    }
    button {
      border: 1px solid var(--border);
      border-radius: 999px;
      background: #fff;
      padding: 8px 14px;
      cursor: pointer;
      font: inherit;
    }
    .ghost {
      background: rgba(255,255,255,0.72);
    }
    button.primary {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
    }
    input[type="range"] {
      flex: 1 1 260px;
      min-width: 220px;
    }
    .pill {
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(15,118,110,0.08);
      color: var(--accent-2);
      font-size: 13px;
    }
    .viewer {
      position: relative;
      overflow: hidden;
      border: 1px solid var(--border);
      border-radius: 16px;
      background: #fffaf2;
      min-height: 420px;
      cursor: grab;
    }
    .viewer-layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 280px;
      gap: 12px;
      align-items: start;
      padding: 12px;
      min-height: 0;
      overflow: auto;
    }
    .viewer-legend {
      position: sticky;
      top: 12px;
      border: 1px solid var(--border);
      border-radius: 16px;
      background: rgba(255,255,255,0.82);
      padding: 16px;
      display: grid;
      gap: 14px;
      backdrop-filter: blur(8px);
    }
    .viewer-legend-title {
      margin: 0;
      font-size: 18px;
    }
    .viewer-legend-stats {
      display: grid;
      gap: 6px;
      color: #243b53;
      font: 13px/1.35 'SFMono-Regular', 'Menlo', monospace;
    }
    .viewer-legend-items {
      display: grid;
      gap: 10px;
    }
    .viewer-legend-item {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 14px;
      color: #243b53;
    }
    .viewer-legend-swatch {
      width: 16px;
      height: 16px;
      border-radius: 4px;
      border: 1px solid #52606d;
      flex: 0 0 auto;
    }
    .axis-overlay {
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 2;
    }
    .axis-corner {
      position: absolute;
      top: 0;
      left: 0;
      width: 42px;
      height: 28px;
      background: rgba(255, 250, 240, 0.92);
      border-right: 1px solid rgba(212, 195, 173, 0.9);
      border-bottom: 1px solid rgba(212, 195, 173, 0.9);
      backdrop-filter: blur(4px);
    }
    .axis-x {
      position: absolute;
      top: 0;
      left: 42px;
      right: 0;
      height: 28px;
      overflow: hidden;
      background: linear-gradient(180deg, rgba(255,250,240,0.96), rgba(255,250,240,0.84));
      border-bottom: 1px solid rgba(212, 195, 173, 0.9);
      backdrop-filter: blur(4px);
    }
    .axis-y {
      position: absolute;
      top: 28px;
      left: 0;
      bottom: 0;
      width: 42px;
      overflow: hidden;
      background: linear-gradient(90deg, rgba(255,250,240,0.96), rgba(255,250,240,0.84));
      border-right: 1px solid rgba(212, 195, 173, 0.9);
      backdrop-filter: blur(4px);
    }
    .axis-label {
      position: absolute;
      color: #52606d;
      font: 11px/1 'SFMono-Regular', 'Menlo', monospace;
      white-space: nowrap;
      transform: translate(-50%, -50%);
    }
    .axis-y .axis-label {
      left: 21px;
      transform: translate(-50%, -50%);
    }
    .viewer.dragging {
      cursor: grabbing;
    }
    #content {
      position: absolute;
      top: 0;
      left: 0;
      transform-origin: 0 0;
      will-change: transform;
    }
    .info {
      padding: 12px 16px;
      border-top: 1px solid var(--border);
      display: grid;
      gap: 10px;
      max-height: 210px;
      overflow: auto;
    }
    pre {
      margin: 0;
      padding: 10px 12px;
      background: #fff;
      border: 1px solid var(--border);
      border-radius: 12px;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
    }
    .logs {
      display: grid;
      gap: 8px;
    }
    .log-item {
      padding: 10px 12px;
      border-radius: 12px;
      background: #fff;
      border: 1px solid var(--border);
      font-size: 13px;
    }
    .empty {
      padding: 20px;
      color: var(--muted);
    }
    @media (max-width: 720px) {
      .toolbar {
        gap: 8px;
      }
      .main-header {
        padding-right: 12px;
      }
      .viewer-layout {
        grid-template-columns: 1fr;
      }
      .viewer-legend {
        position: static;
      }
    }
  </style>
</head>
<body>
  <div class="app sidebar-collapsed" id="app">
    <section class="panel sidebar">
      <div class="sidebar-header">
        <div class="sidebar-header-copy">
          <h1 class="title">DatsSol Sessions</h1>
          <p class="subtitle">Записанные раунды и покадровый просмотр.</p>
        </div>
        <button id="closeSidebarBtn" class="ghost" type="button">Скрыть</button>
      </div>
      <div id="sessionList"></div>
    </section>
    <section class="panel main">
      <div class="main-header">
        <button id="openSidebarBtn" class="ghost" type="button">Сессии</button>
        <div class="header-copy">
          <h2 id="sessionTitle" class="title">Выбери сессию</h2>
          <p id="sessionSubtitle" class="subtitle">Список сессий открывается кнопкой «Сессии».</p>
        </div>
      </div>
      <div class="toolbar">
        <button id="prevBtn">← Prev</button>
        <button id="playBtn" class="primary">Play</button>
        <button id="nextBtn">Next →</button>
        <input id="frameSlider" type="range" min="0" max="0" value="0" />
        <button id="zoomOutBtn">-</button>
        <button id="zoomInBtn">+</button>
        <button id="centerHqBtn">ЦУ</button>
        <button id="fitBtn">Fit</button>
        <span id="frameStatus" class="pill">No frame</span>
      </div>
      <div class="viewer-layout">
        <div id="viewer" class="viewer">
          <div id="content"></div>
          <div class="axis-overlay" id="axisOverlay">
            <div class="axis-corner"></div>
            <div class="axis-x" id="xAxis"></div>
            <div class="axis-y" id="yAxis"></div>
          </div>
        </div>
        <aside id="viewerLegend" class="viewer-legend">
          <h3 class="viewer-legend-title">Legend</h3>
          <div class="viewer-legend-stats">
            <div>Выберите кадр.</div>
          </div>
          <div class="viewer-legend-items"></div>
        </aside>
      </div>
      <div class="info">
        <div id="frameMeta" class="subtitle">Нет выбранного кадра.</div>
        <div id="frameLogs" class="logs"></div>
        <pre id="framePayload">decision/response появятся здесь</pre>
      </div>
    </section>
  </div>
  <script>
    const appEl = document.getElementById('app');
    const sessionListEl = document.getElementById('sessionList');
    const sessionTitleEl = document.getElementById('sessionTitle');
    const sessionSubtitleEl = document.getElementById('sessionSubtitle');
    const frameStatusEl = document.getElementById('frameStatus');
    const frameMetaEl = document.getElementById('frameMeta');
    const frameLogsEl = document.getElementById('frameLogs');
    const framePayloadEl = document.getElementById('framePayload');
    const contentEl = document.getElementById('content');
    const viewerEl = document.getElementById('viewer');
    const viewerLegendEl = document.getElementById('viewerLegend');
    const xAxisEl = document.getElementById('xAxis');
    const yAxisEl = document.getElementById('yAxis');
    const sliderEl = document.getElementById('frameSlider');
    const playBtn = document.getElementById('playBtn');
    const openSidebarBtn = document.getElementById('openSidebarBtn');
    const closeSidebarBtn = document.getElementById('closeSidebarBtn');
    let sessions = [];
    let currentSession = null;
    let currentIndex = 0;
    let scale = 1;
    let translateX = 18;
    let translateY = 18;
    let timer = null;
    let dragging = false;
    let dragStartX = 0;
    let dragStartY = 0;
    const ZOOM_FACTOR = 1.15;
    const DEFAULT_ZOOM_IN_STEPS = 8;

    function getAxisConfig(svg) {
      if (!svg) return null;
      const width = Number(svg.dataset.gridWidth || 0);
      const height = Number(svg.dataset.gridHeight || 0);
      const cellSize = Number(svg.dataset.cellSize || 0);
      const margin = Number(svg.dataset.gridMargin || 0);
      if (!width || !height || !cellSize) {
        return null;
      }
      return {
        width,
        height,
        cellSize,
        margin,
        step: Math.max(1, Math.ceil(Math.max(width, height, 1) / 12)),
      };
    }

    function renderStickyAxes() {
      const svg = contentEl.querySelector('svg');
      const axis = getAxisConfig(svg);
      xAxisEl.innerHTML = '';
      yAxisEl.innerHTML = '';
      if (!axis) {
        return;
      }

      for (let x = 0; x < axis.width; x += axis.step) {
        const label = document.createElement('div');
        label.className = 'axis-label';
        label.textContent = String(x);
        label.style.left = `${translateX + (axis.margin + x * axis.cellSize + axis.cellSize / 2) * scale - 42}px`;
        label.style.top = '14px';
        xAxisEl.appendChild(label);
      }

      for (let y = 0; y < axis.height; y += axis.step) {
        const label = document.createElement('div');
        label.className = 'axis-label';
        label.textContent = String(y);
        label.style.top = `${translateY + (axis.margin + y * axis.cellSize + axis.cellSize / 2) * scale - 28}px`;
        yAxisEl.appendChild(label);
      }
    }

    function setSidebarCollapsed(collapsed) {
      appEl.classList.toggle('sidebar-collapsed', collapsed);
    }

    function applyTransform() {
      contentEl.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
      renderStickyAxes();
    }

    function fitView(scaleMultiplier = 1) {
      const svg = contentEl.querySelector('svg');
      if (!svg) {
        scale = 1;
        translateX = 18;
        translateY = 18;
        applyTransform();
        return;
      }
      const vb = svg.viewBox.baseVal;
      const padding = 24;
      const availableWidth = Math.max(viewerEl.clientWidth - padding * 2, 1);
      const availableHeight = Math.max(viewerEl.clientHeight - padding * 2, 1);
      scale = Math.min(
        Math.max(availableWidth, availableHeight) / Math.max(vb.width, vb.height),
        1
      );
      scale = Math.max(0.08, Math.min(scale * scaleMultiplier, 10));
      translateX = (viewerEl.clientWidth - vb.width * scale) / 2;
      translateY = (viewerEl.clientHeight - vb.height * scale) / 2;
      applyTransform();
    }

    function resetViewport() {
      fitView(ZOOM_FACTOR ** DEFAULT_ZOOM_IN_STEPS);
      centerOnHq();
    }

    function centerOnHq() {
      if (!currentSession || !currentSession.frames.length) return;
      const frame = currentSession.frames[currentIndex];
      const hqPosition = frame?.hqPosition;
      const svg = contentEl.querySelector('svg');
      const axis = getAxisConfig(svg);
      if (!axis || !Array.isArray(hqPosition) || hqPosition.length !== 2) {
        return;
      }
      const [hqX, hqY] = hqPosition;
      const targetX = axis.margin + (hqX + 0.5) * axis.cellSize;
      const targetY = axis.margin + (hqY + 0.5) * axis.cellSize;
      translateX = viewerEl.clientWidth / 2 - targetX * scale;
      translateY = viewerEl.clientHeight / 2 - targetY * scale;
      applyTransform();
    }

    function stopPlayback() {
      if (!timer) return;
      clearInterval(timer);
      timer = null;
      playBtn.textContent = 'Play';
    }

    function renderLegend(frame) {
      const legend = frame?.legend;
      if (!legend) {
        viewerLegendEl.innerHTML = `
          <h3 class="viewer-legend-title">Legend</h3>
          <div class="viewer-legend-stats"><div>Нет данных для легенды.</div></div>
          <div class="viewer-legend-items"></div>
        `;
        return;
      }

      const stats = Array.isArray(legend.stats) ? legend.stats : [];
      const items = Array.isArray(legend.items) ? legend.items : [];
      viewerLegendEl.innerHTML = `
        <h3 class="viewer-legend-title">${legend.title || 'Legend'}</h3>
        <div class="viewer-legend-stats">
          ${stats.map((line) => `<div>${line}</div>`).join('')}
        </div>
        <div class="viewer-legend-items">
          ${items.map((item) => `
            <div class="viewer-legend-item">
              <span class="viewer-legend-swatch" style="background:${item.color || '#fff'}"></span>
              <span>${item.label || ''}</span>
            </div>
          `).join('')}
        </div>
      `;
    }

    function renderFrame(index, preserveTransform = true) {
      if (!currentSession || !currentSession.frames.length) {
        contentEl.innerHTML = '<div class="empty">В этой сессии нет кадров.</div>';
        frameStatusEl.textContent = 'No frame';
        frameMetaEl.textContent = 'Нет выбранного кадра.';
        frameLogsEl.innerHTML = '';
        framePayloadEl.textContent = 'decision/response появятся здесь';
        renderLegend(null);
        return;
      }

      currentIndex = Math.max(0, Math.min(index, currentSession.frames.length - 1));
      const frame = currentSession.frames[currentIndex];
      sliderEl.value = String(currentIndex);
      contentEl.innerHTML = frame.svg;
      renderLegend(frame);
      frameStatusEl.textContent =
        `turn ${frame.turnNo} • ${currentIndex + 1}/${currentSession.frames.length} • plantations ${frame.plantations} • cells ${frame.cells}`;
      frameMetaEl.textContent =
        `capturedAt: ${frame.capturedAt || '?'} | nextTurnIn: ${frame.nextTurnIn ?? '?'} | hqId: ${frame.hqId || '?'} | hqHp: ${frame.hqHp ?? '?'} | decisionMs: ${frame.strategyElapsedMs ?? '?'} | submitMs: ${frame.submitElapsedMs ?? '?'}`;
      framePayloadEl.textContent = JSON.stringify(
        { decision: frame.decision, response: frame.response },
        null,
        2
      );
      frameLogsEl.innerHTML = '';
      if (frame.logs.length === 0) {
        frameLogsEl.innerHTML = '<div class="empty">На этот ход нет логов.</div>';
      } else {
        for (const log of frame.logs) {
          const div = document.createElement('div');
          div.className = 'log-item';
          div.textContent = `${log.time || '?'} | ${log.message || ''}`;
          frameLogsEl.appendChild(div);
        }
      }
      if (!preserveTransform) {
        fitView();
      } else {
        applyTransform();
      }
    }

    function renderSessionButtons() {
      sessionListEl.innerHTML = '';
      if (sessions.length === 0) {
        sessionListEl.innerHTML = '<div class="empty">Сессий пока нет.</div>';
        return;
      }
      for (const session of sessions) {
        const btn = document.createElement('button');
        btn.className = 'session-btn';
        btn.dataset.sessionId = session.id;
        btn.innerHTML = `
          <div><strong>${session.label}</strong></div>
          <div class="session-meta">
            hqId: ${session.hqId || '?'}<br/>
            frames: ${session.frameCount} | turns: ${session.firstTurn ?? '?'}..${session.lastTurn ?? '?'}<br/>
            strategy: ${session.strategy || '?'} | logs: ${session.logCount}<br/>
            latencyAvg: ${session.latencyAvg ?? '?'}s | startedAt: ${session.startedAt || '?'}
          </div>
        `;
        btn.addEventListener('click', () => loadSession(session.id));
        sessionListEl.appendChild(btn);
      }
    }

    function markActiveSession(sessionId) {
      for (const node of sessionListEl.querySelectorAll('.session-btn')) {
        node.classList.toggle('active', node.dataset.sessionId === sessionId);
      }
    }

    async function loadSessions() {
      const response = await fetch('/api/sessions');
      sessions = await response.json();
      sessions.sort((a, b) => {
        const aTs = Number(a.createdTs || 0);
        const bTs = Number(b.createdTs || 0);
        if (aTs !== bTs) return bTs - aTs;
        return String(b.id || '').localeCompare(String(a.id || ''));
      });
      renderSessionButtons();
      if (sessions.length > 0) {
        const latestSession = sessions[0];
        await loadSession(latestSession.id);
      }
    }

    async function loadSession(sessionId) {
      stopPlayback();
      const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`);
      currentSession = await response.json();
      currentIndex = 0;
      sliderEl.max = String(Math.max(currentSession.frames.length - 1, 0));
      sessionTitleEl.textContent = currentSession.label;
      sessionSubtitleEl.textContent =
        `${currentSession.path} | strategy: ${currentSession.meta.strategy || '?'} | logs: ${currentSession.logCount}`;
      markActiveSession(sessionId);
      setSidebarCollapsed(true);
      renderFrame(0, true);
      resetViewport();
    }

    function nextFrame() {
      if (!currentSession || currentSession.frames.length === 0) return;
      renderFrame((currentIndex + 1) % currentSession.frames.length, true);
    }

    function prevFrame() {
      if (!currentSession || currentSession.frames.length === 0) return;
      renderFrame((currentIndex - 1 + currentSession.frames.length) % currentSession.frames.length, true);
    }

    function togglePlayback() {
      if (!currentSession || currentSession.frames.length === 0) return;
      if (timer) {
        stopPlayback();
        return;
      }
      timer = setInterval(() => nextFrame(), 800);
      playBtn.textContent = 'Pause';
    }

    document.getElementById('prevBtn').addEventListener('click', () => prevFrame());
    document.getElementById('nextBtn').addEventListener('click', () => nextFrame());
    document.getElementById('playBtn').addEventListener('click', () => togglePlayback());
    document.getElementById('zoomInBtn').addEventListener('click', () => { scale *= ZOOM_FACTOR; applyTransform(); });
    document.getElementById('zoomOutBtn').addEventListener('click', () => { scale /= ZOOM_FACTOR; applyTransform(); });
    document.getElementById('centerHqBtn').addEventListener('click', () => centerOnHq());
    document.getElementById('fitBtn').addEventListener('click', () => fitView());
    openSidebarBtn.addEventListener('click', () => setSidebarCollapsed(false));
    closeSidebarBtn.addEventListener('click', () => setSidebarCollapsed(true));
    sliderEl.addEventListener('input', (event) => renderFrame(Number(event.target.value), true));

    viewerEl.addEventListener('wheel', (event) => {
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.1 : 1 / 1.1;
      scale = Math.max(0.08, Math.min(scale * factor, 10));
      applyTransform();
    }, { passive: false });

    viewerEl.addEventListener('mousedown', (event) => {
      dragging = true;
      viewerEl.classList.add('dragging');
      dragStartX = event.clientX - translateX;
      dragStartY = event.clientY - translateY;
    });

    window.addEventListener('mousemove', (event) => {
      if (!dragging) return;
      translateX = event.clientX - dragStartX;
      translateY = event.clientY - dragStartY;
      applyTransform();
    });

    window.addEventListener('mouseup', () => {
      dragging = false;
      viewerEl.classList.remove('dragging');
    });

    window.addEventListener('resize', () => renderStickyAxes());

    window.addEventListener('keydown', (event) => {
      if (event.key === ' ') {
        event.preventDefault();
        togglePlayback();
      } else if (event.key === 'ArrowRight') {
        nextFrame();
      } else if (event.key === 'ArrowLeft') {
        prevFrame();
      }
    });

    loadSessions();
  </script>
</body>
</html>
"""


class SessionRequestHandler(BaseHTTPRequestHandler):
    server: "SessionHTTPServer"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.respond_html(render_index_html())
            return
        if parsed.path == "/api/sessions":
            payload = list_sessions(self.server.app_config.sessions_dir)
            self.respond_json(payload)
            return
        if parsed.path.startswith("/api/sessions/"):
            session_id = parsed.path.removeprefix("/api/sessions/")
            self.handle_session_details(session_id)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "not found")

    def log_message(self, format: str, *args: Any) -> None:
        return

    def handle_session_details(self, session_id: str) -> None:
        session_path = self.server.app_config.sessions_dir / session_id
        if not session_path.exists() or not session_path.is_dir():
            self.send_error(HTTPStatus.NOT_FOUND, "session not found")
            return
        if not (session_path / "turns.jsonl").exists():
            self.send_error(HTTPStatus.NOT_FOUND, "turns.jsonl not found")
            return
        payload = load_session(str(session_path.resolve()), self.server.app_config.cell_size)
        self.respond_json(payload)

    def respond_html(self, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def respond_json(self, payload: Any) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class SessionHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_cls: type[BaseHTTPRequestHandler], app_config: AppConfig):
        super().__init__(server_address, handler_cls)
        self.app_config = app_config


def main() -> int:
    args = parse_args()
    app_config = AppConfig(
        sessions_dir=args.sessions_dir.resolve(),
        cell_size=args.cell_size,
    )
    httpd = SessionHTTPServer((args.host, args.port), SessionRequestHandler, app_config)
    print(f"Serving DatsSol sessions on http://{args.host}:{args.port}")
    print(f"Sessions dir: {app_config.sessions_dir}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
