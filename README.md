# DatsSol Bot

Python-проект для хакатона DatsSol: бот для пошаговой стратегии и утилиты для работы с картой.

Спецификации:
- [Правила игры](/Users/alexandrfedorov/src/hackatons/2026-04-17_dats_sol/docs/specs/dats_sol_spec.md)
- [OpenAPI](/Users/alexandrfedorov/src/hackatons/2026-04-17_dats_sol/docs/specs/openapi.yml)

## Разворачивание

Требования:
- Python 3.14+
- доступ к токену `DATS_TOKEN`

Установка с нуля:

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env
```

После этого заполни `.env`:

```dotenv
DATS_TOKEN=your_token_here
# опционально
DATS_BASE_URL=https://games-test.datsteam.dev
```

Проверка окружения:

```bash
./venv/bin/python -m pytest
```

Примечания:
- все команды в проекте нужно запускать через `venv/bin/python`
- HTTP/2 для `httpx` включается через зависимость `h2`, она уже добавлена в `requirements.txt`
- клиент использует keep-alive и пытается переиспользовать соединения между запросами

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

## Web Viewer для сессий

Скрипт [scripts/session_viewer.py](/Users/alexandrfedorov/src/hackatons/2026-04-17_dats_sol/scripts/session_viewer.py:1) поднимает локальный HTTP-сервер и показывает записанные игровые сессии из `artifacts/sessions`.

Базовый запуск:

```bash
venv/bin/python scripts/session_viewer.py
```

После запуска открой:

```text
http://127.0.0.1:8765
```

Полезные опции:

```bash
venv/bin/python scripts/session_viewer.py --host 0.0.0.0 --port 9000
venv/bin/python scripts/session_viewer.py --sessions-dir /tmp/dats_sol_sessions
venv/bin/python scripts/session_viewer.py --cell-size 24
```

В интерфейсе доступны:
- список всех записанных сессий
- покадровое переключение ходов
- autoplay
- zoom in/out и fit
- drag/pan мышью
- логи, привязанные к конкретному ходу
- `decision/response` для каждого кадра

## Recorder и управление стратегией

Скрипт [scripts/run_session.py](/Users/alexandrfedorov/src/hackatons/2026-04-17_dats_sol/scripts/run_session.py:1) запускает session recorder. Стратегия выбирается явно через `--strategy`.

Сейчас доступны:
- `passive` — [PassiveStrategy](/Users/alexandrfedorov/src/hackatons/2026-04-17_dats_sol/cherviak/strategies/passive.py:1), ничего не отправляет и только пишет историю арены и логов
- `lateral` — [LateralStrategy](/Users/alexandrfedorov/src/hackatons/2026-04-17_dats_sol/cherviak/strategies/lateral.py:1), «рыба-червяк» с боковыми ответвлениями

Как этим управлять:
- для безопасного dry-run запускай без `--submit`
- чтобы стратегия реально отправляла команды, добавь `--submit`
- если `--strategy` не указан, скрипт покажет список доступных стратегий
- в консоль логика раннера пишет сообщения уровня `INFO`
- HTTP-запросы и ответы пишутся на уровне `DEBUG`
- для каждого нового хода в лог попадает `decision_time_ms` — сколько стратегия думала над `decide_turn`

Примеры:

```bash
venv/bin/python scripts/run_session.py --strategy passive
venv/bin/python scripts/run_session.py --strategy passive --logs-interval 3
venv/bin/python scripts/run_session.py --strategy passive --submit
venv/bin/python scripts/run_session.py --strategy lateral --submit
```

Что пишет:
- `artifacts/sessions/<session_id>/meta.json`
- `artifacts/sessions/<session_id>/turns.jsonl`
- `artifacts/sessions/<session_id>/logs.jsonl`

## Анализ игровых логов

Скрипт [scripts/analyze_logs.py](/Users/alexandrfedorov/src/hackatons/2026-04-17_dats_sol/scripts/analyze_logs.py:1) делает запрос к `GET /api/logs` или читает локальный JSON с логами, после чего строит короткую сводку:

- сколько и каких событий было
- что по логам похоже на состояние ЦУ
- какие апгрейды встречались
- последние важные события

Примеры:

```bash
venv/bin/python scripts/analyze_logs.py
venv/bin/python scripts/analyze_logs.py --save-raw
venv/bin/python scripts/analyze_logs.py --input-json artifacts/logs/player_logs_20260417_120000.json
```
