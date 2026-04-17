# DatsSol Bot

Python-проект для хакатона DatsSol: бот для пошаговой стратегии и утилиты для работы с картой.

Спецификации:
- [Правила игры](/Users/alexandrfedorov/src/hackatons/2026-04-17_dats_sol/docs/specs/dats_sol_spec.md)
- [OpenAPI](/Users/alexandrfedorov/src/hackatons/2026-04-17_dats_sol/docs/specs/openapi.yml)

## Подготовка

Скопируй пример переменных окружения и укажи токен:

```bash
cp .env.example .env
```

Поддерживаемые переменные:
- `DATS_TOKEN` — токен игрока
- `DATS_BASE_URL` — базовый URL сервера, по умолчанию `https://games-test.datsteam.dev`

Все команды запускай через локальный Python из `venv/`.

## Запуск бота

Сейчас основной файл проекта:

```bash
venv/bin/python main.py
```

## Получение карты и визуализация

Скрипт [scripts/get_map.py](/Users/alexandrfedorov/src/hackatons/2026-04-17_dats_sol/scripts/get_map.py:1) делает запрос к `GET /api/arena`, сохраняет snapshot в JSON и рендерит SVG-карту.

Базовый запуск:

```bash
venv/bin/python scripts/get_map.py
```

Что получится:
- `artifacts/map/arena_turn_<N>.json` — сырой ответ API
- `artifacts/map/arena_turn_<N>.svg` — визуализация карты

Полезные опции:

```bash
venv/bin/python scripts/get_map.py --base-url https://games.datsteam.dev
venv/bin/python scripts/get_map.py --output-dir /tmp/dats_sol_map
venv/bin/python scripts/get_map.py --cell-size 24
venv/bin/python scripts/get_map.py --input-json /path/to/arena.json
```

В SVG отмечаются:
- горы
- бонусные клетки (`x % 7 == 0` и `y % 7 == 0`)
- свои плантации и ЦУ
- вражеские плантации
- стройки
- бобры
- прогресс терраформированных клеток
- прогноз катаклизмов в легенде справа
