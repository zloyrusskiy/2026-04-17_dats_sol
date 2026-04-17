#!/usr/bin/env python3
"""Fetch the current arena state and render an SVG map snapshot."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://games-test.datsteam.dev"
DEFAULT_OUTPUT_DIR = Path("artifacts/map")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Получить карту DatsSol и сохранить JSON + SVG визуализацию."
    )
    parser.add_argument(
        "--input-json",
        type=Path,
        help="Готовый snapshot арены. Если указан, запрос к API не выполняется.",
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
        help=f"Куда сохранить результат. По умолчанию {DEFAULT_OUTPUT_DIR}.",
    )
    parser.add_argument(
        "--cell-size",
        type=int,
        default=18,
        help="Размер клетки в пикселях.",
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
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


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


def fetch_arena(base_url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url}/api/arena",
        headers={
            "X-Auth-Token": token,
            "Accept": "application/json",
            "User-Agent": "dats-sol-map-fetcher/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Ошибка API: HTTP {exc.code}\n{body}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Не удалось подключиться к API: {exc.reason}") from exc


def svg_rect(x: float, y: float, width: float, height: float, **attrs: Any) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}"'
        f'{format_attrs(attrs)} />'
    )


def svg_circle(cx: float, cy: float, r: float, **attrs: Any) -> str:
    return f'<circle cx="{cx}" cy="{cy}" r="{r}"{format_attrs(attrs)} />'


def svg_text(x: float, y: float, text: str, **attrs: Any) -> str:
    escaped = (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return f'<text x="{x}" y="{y}"{format_attrs(attrs)}>{escaped}</text>'


def svg_polygon(points: list[tuple[float, float]], **attrs: Any) -> str:
    points_text = " ".join(f"{x},{y}" for x, y in points)
    return f'<polygon points="{points_text}"{format_attrs(attrs)} />'


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


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def progress_color(progress: int) -> str:
    ratio = clamp(progress / 100.0, 0.0, 1.0)
    red = int(225 - ratio * 120)
    green = int(235 - ratio * 35)
    blue = int(225 - ratio * 145)
    return f"rgb({red},{green},{blue})"


def render_svg(arena: dict[str, Any], cell_size: int) -> str:
    width, height = arena["size"]
    margin = 42
    legend_width = 270
    map_width = width * cell_size
    map_height = height * cell_size
    canvas_width = map_width + margin * 2 + legend_width
    canvas_height = map_height + margin * 2

    def cell_origin(x: int, y: int) -> tuple[int, int]:
        return margin + x * cell_size, margin + y * cell_size

    def cell_center(x: int, y: int) -> tuple[float, float]:
        ox, oy = cell_origin(x, y)
        return ox + cell_size / 2, oy + cell_size / 2

    svg: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width}" '
            f'height="{canvas_height}" viewBox="0 0 {canvas_width} {canvas_height}">'
        ),
        "<style>",
        "text { font-family: 'SFMono-Regular', 'Menlo', monospace; }",
        ".small { font-size: 11px; fill: #52606d; }",
        ".label { font-size: 12px; fill: #102a43; }",
        ".title { font-size: 20px; font-weight: bold; fill: #102a43; }",
        ".legend { font-size: 13px; fill: #243b53; }",
        "</style>",
        svg_rect(0, 0, canvas_width, canvas_height, fill="#f4f7fb"),
        svg_rect(margin, margin, map_width, map_height, fill="#ffffff", stroke="#bcccdc"),
    ]

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

    axis_step = max(1, math.ceil(max(width, height) / 12))
    for x in range(width):
        if x % axis_step == 0:
            xpos = margin + x * cell_size + cell_size / 2
            svg.append(svg_text(xpos, margin - 10, str(x), class_="small", text_anchor="middle"))
    for y in range(height):
        if y % axis_step == 0:
            ypos = margin + y * cell_size + cell_size / 2 + 4
            svg.append(svg_text(margin - 10, ypos, str(y), class_="small", text_anchor="end"))

    for y in range(height):
        for x in range(width):
            if x % 7 == 0 and y % 7 == 0:
                ox, oy = cell_origin(x, y)
                svg.append(
                    svg_rect(
                        ox + 1,
                        oy + 1,
                        cell_size - 2,
                        cell_size - 2,
                        fill="#fff7d6",
                    )
                )

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
        svg.append(
            svg_text(
                cx,
                cy + 4,
                str(construction["progress"]),
                class_="small",
                fill="#102a43",
                text_anchor="middle",
            )
        )

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
                svg_polygon(
                    points,
                    fill="#f0b429",
                    stroke="#8d2b0b",
                    stroke_width="1.5",
                )
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

    legend_x = margin + map_width + 24
    legend_y = margin
    svg.append(svg_text(legend_x, legend_y, "DatsSol Arena Snapshot", class_="title"))

    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    info_lines = [
        f"turn: {arena.get('turnNo', '?')}",
        f"size: {width}x{height}",
        f"actionRange: {arena.get('actionRange', '?')}",
        f"nextTurnIn: {arena.get('nextTurnIn', '?')}",
        f"snapshot: {timestamp}",
    ]
    for index, line in enumerate(info_lines, start=1):
        svg.append(svg_text(legend_x, legend_y + 24 + index * 18, line, class_="legend"))

    legend_items = [
        ("#fff7d6", "bonus cell (x,y кратны 7)"),
        ("#7b8794", "mountain"),
        ("#9fd4a3", "terraformed cell"),
        ("#9fb3ff", "construction"),
        ("#0e9f6e", "your plantation"),
        ("#f0b429", "your HQ"),
        ("#d64545", "enemy plantation"),
        ("#8d6e63", "beaver"),
    ]
    base_y = legend_y + 150
    for index, (color, label) in enumerate(legend_items):
        item_y = base_y + index * 28
        svg.append(svg_rect(legend_x, item_y - 12, 16, 16, fill=color, stroke="#52606d"))
        svg.append(svg_text(legend_x + 26, item_y, label, class_="legend"))

    forecast_y = base_y + len(legend_items) * 28 + 20
    svg.append(svg_text(legend_x, forecast_y, "meteo:", class_="label"))
    for index, forecast in enumerate(arena.get("meteoForecasts", []), start=1):
        bits = [forecast.get("kind", "unknown")]
        if "turnsUntil" in forecast:
            bits.append(f"T-{forecast['turnsUntil']}")
        if "position" in forecast and forecast["position"] is not None:
            bits.append(f"pos={forecast['position']}")
        if "radius" in forecast:
            bits.append(f"r={forecast['radius']}")
        if forecast.get("forming") is True:
            bits.append("forming")
        svg.append(
            svg_text(
                legend_x,
                forecast_y + index * 18,
                " | ".join(bits),
                class_="legend",
            )
        )

    svg.append("</svg>")
    return "\n".join(svg)


def save_snapshot(arena: dict[str, Any], output_dir: Path, cell_size: int) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    turn_no = arena.get("turnNo", "unknown")
    json_path = output_dir / f"arena_turn_{turn_no}.json"
    svg_path = output_dir / f"arena_turn_{turn_no}.svg"

    json_path.write_text(
        json.dumps(arena, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    svg_path.write_text(render_svg(arena, cell_size), encoding="utf-8")
    return json_path, svg_path


def main() -> int:
    args = parse_args()
    load_dotenv(Path(".env"))

    if args.input_json:
        arena = json.loads(args.input_json.read_text(encoding="utf-8"))
    else:
        token = get_token(args.token)
        base_url = get_base_url(args.base_url)
        arena = fetch_arena(base_url, token)

    json_path, svg_path = save_snapshot(arena, args.output_dir, args.cell_size)

    print(f"JSON saved to: {json_path}")
    print(f"SVG saved to: {svg_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
