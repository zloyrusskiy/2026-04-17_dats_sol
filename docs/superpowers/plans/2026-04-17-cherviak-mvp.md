# Червяк v1 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Working DatsSol bot in ~1 hour using «Червяк» strategy (HQ moves forward in chain, builds adjacent cells, relocates each cycle).

**Architecture:** Small Python package `cherviak/` with one responsibility per module: config, models, HTTP client, pure decision logic. Thin entry point `main.py` runs the game loop. Pure functions in `brain.py` are unit-tested with pytest; HTTP/loop is smoke-tested manually against the test server.

**Tech Stack:** Python 3.10+, `httpx` (sync HTTP), `pydantic` v2 (typed models with camelCase aliases), `tenacity` (retries), `python-dotenv` (.env), `loguru` (logging), `pytest` (tests).

**Reference spec:** `docs/superpowers/specs/2026-04-17-strategy-and-cherviak-mvp.md`

---

## File Structure

```
2026-04-17_dats_sol/
├── main.py                       # entry: load config → loop arena/decide/command
├── cherviak/
│   ├── __init__.py
│   ├── config.py                 # load .env into Config dataclass
│   ├── models.py                 # pydantic Arena + sub-models with camelCase aliases
│   ├── client.py                 # GameClient (httpx + tenacity)
│   └── brain.py                  # pure decision functions: pick_target, build_commands, check_relocate, pick_upgrade, decide_turn
├── tests/
│   ├── __init__.py
│   ├── test_models.py            # parse a sample arena JSON
│   └── test_brain.py             # pure logic unit tests
├── requirements.txt              # locked deps
└── pytest.ini                    # pytest config (rootdir, testpaths)
```

**Boundaries:**
- `models.py` — only data definitions, no logic
- `client.py` — only HTTP I/O, no decisions
- `brain.py` — only pure functions of `Arena → decisions`, no I/O
- `main.py` — only orchestration glue

---

## Task 1: Scaffold project and dependencies

**Files:**
- Create: `requirements.txt`
- Create: `pytest.ini`
- Create: `cherviak/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Write `requirements.txt`**

```
httpx>=0.27,<1.0
pydantic>=2.5,<3.0
tenacity>=8.0,<10.0
python-dotenv>=1.0
loguru>=0.7
pytest>=8.0
```

- [ ] **Step 2: Install dependencies**

Run: `venv/bin/pip install -r requirements.txt`
Expected: all packages install without errors.

- [ ] **Step 3: Write `pytest.ini`**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -v
```

- [ ] **Step 4: Create empty package files**

```bash
touch cherviak/__init__.py tests/__init__.py
```

- [ ] **Step 5: Verify pytest works on empty test dir**

Run: `venv/bin/pytest`
Expected: `no tests ran` (exit code 5) — pytest is installed and can find the dir.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt pytest.ini cherviak/__init__.py tests/__init__.py
git commit -m "chore: scaffold cherviak package and pytest config"
```

---

## Task 2: Config module

**Files:**
- Create: `cherviak/config.py`
- Modify: `.env.example` (add expected keys)

- [ ] **Step 1: Write `.env.example`**

Open `.env.example` and replace its content with:

```
DATS_TOKEN=your-token-here
DATS_BASE_URL=https://games-test.datsteam.dev
```

- [ ] **Step 2: Write `cherviak/config.py`**

```python
import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    token: str
    base_url: str


def load_config() -> Config:
    load_dotenv()
    token = os.environ.get("DATS_TOKEN", "").strip()
    base_url = os.environ.get("DATS_BASE_URL", "https://games-test.datsteam.dev").strip()
    if not token:
        raise RuntimeError("DATS_TOKEN is not set in .env or environment")
    return Config(token=token, base_url=base_url)
```

- [ ] **Step 3: Smoke-test config loads**

Ensure `.env` exists with a real token (already present per project state). Run:

```bash
venv/bin/python -c "from cherviak.config import load_config; c = load_config(); print(c.base_url, len(c.token))"
```

Expected: prints base URL and a non-zero token length.

- [ ] **Step 4: Commit**

```bash
git add .env.example cherviak/config.py
git commit -m "feat: add config loader with .env support"
```

---

## Task 3: Pydantic models for Arena response (TDD)

**Files:**
- Create: `tests/test_models.py`
- Create: `cherviak/models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_models.py`:

```python
from cherviak.models import Arena


SAMPLE_ARENA = {
    "turnNo": 42,
    "nextTurnIn": 0.85,
    "size": [100, 100],
    "actionRange": 2,
    "plantations": [
        {
            "id": "p1",
            "position": [50, 50],
            "isMain": True,
            "isIsolated": False,
            "immunityUntilTurn": 45,
            "hp": 50,
        },
        {
            "id": "p2",
            "position": [50, 51],
            "isMain": False,
            "isIsolated": False,
            "immunityUntilTurn": 0,
            "hp": 50,
        },
    ],
    "enemy": [],
    "mountains": [[10, 10], [11, 10]],
    "cells": [
        {"position": [50, 50], "terraformationProgress": 25, "turnsUntilDegradation": 80}
    ],
    "construction": [{"position": [50, 52], "progress": 30}],
    "beavers": [{"id": "b1", "position": [70, 70], "hp": 100}],
    "plantationUpgrades": {
        "points": 1,
        "intervalTurns": 30,
        "turnsUntilPoints": 18,
        "maxPoints": 15,
        "tiers": [
            {"name": "repair_power", "current": 0, "max": 3},
            {"name": "settlement_limit", "current": 0, "max": 10},
        ],
    },
    "meteoForecasts": [
        {"kind": "earthquake", "turnsUntil": 5}
    ],
}


def test_arena_parses_camelcase_fields():
    arena = Arena.model_validate(SAMPLE_ARENA)
    assert arena.turn_no == 42
    assert arena.next_turn_in == 0.85
    assert arena.action_range == 2
    assert arena.size == [100, 100]


def test_arena_parses_plantations():
    arena = Arena.model_validate(SAMPLE_ARENA)
    assert len(arena.plantations) == 2
    hq = arena.plantations[0]
    assert hq.is_main is True
    assert hq.is_isolated is False
    assert hq.immunity_until_turn == 45
    assert hq.position == [50, 50]


def test_arena_parses_upgrades():
    arena = Arena.model_validate(SAMPLE_ARENA)
    pu = arena.plantation_upgrades
    assert pu.points == 1
    assert pu.max_points == 15
    assert len(pu.tiers) == 2
    assert pu.tiers[0].name == "repair_power"


def test_arena_parses_meteo_with_optional_fields():
    arena = Arena.model_validate(SAMPLE_ARENA)
    assert len(arena.meteo_forecasts) == 1
    eq = arena.meteo_forecasts[0]
    assert eq.kind == "earthquake"
    assert eq.turns_until == 5
    assert eq.position is None
    assert eq.radius is None


def test_arena_handles_missing_optional_lists():
    minimal = {
        "turnNo": 1,
        "nextTurnIn": 1.0,
        "size": [100, 100],
        "actionRange": 2,
        "plantationUpgrades": {
            "points": 0, "intervalTurns": 30, "turnsUntilPoints": 30,
            "maxPoints": 15, "tiers": [],
        },
    }
    arena = Arena.model_validate(minimal)
    assert arena.plantations == []
    assert arena.beavers == []
    assert arena.meteo_forecasts == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_models.py -v`
Expected: ImportError or ModuleNotFoundError for `cherviak.models`.

- [ ] **Step 3: Write `cherviak/models.py`**

```python
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


Position = list[int]  # [x, y]


class Plantation(BaseModel):
    id: str
    position: Position
    is_main: bool = Field(alias="isMain")
    is_isolated: bool = Field(alias="isIsolated")
    immunity_until_turn: int = Field(alias="immunityUntilTurn")
    hp: int


class Enemy(BaseModel):
    id: str
    position: Position
    hp: int


class Construction(BaseModel):
    position: Position
    progress: int


class Beaver(BaseModel):
    id: str
    position: Position
    hp: int


class Cell(BaseModel):
    position: Position
    terraformation_progress: int = Field(alias="terraformationProgress")
    turns_until_degradation: int = Field(alias="turnsUntilDegradation")


class UpgradeTier(BaseModel):
    name: str
    current: int
    max: int


class PlantationUpgrades(BaseModel):
    points: int
    interval_turns: int = Field(alias="intervalTurns")
    turns_until_points: int = Field(alias="turnsUntilPoints")
    max_points: int = Field(alias="maxPoints")
    tiers: list[UpgradeTier]


class MeteoForecast(BaseModel):
    kind: str
    turns_until: int = Field(alias="turnsUntil")
    id: Optional[str] = None
    forming: Optional[bool] = None
    position: Optional[Position] = None
    next_position: Optional[Position] = Field(default=None, alias="nextPosition")
    radius: Optional[int] = None


class Arena(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    turn_no: int = Field(alias="turnNo")
    next_turn_in: float = Field(alias="nextTurnIn")
    size: list[int]
    action_range: int = Field(alias="actionRange")
    plantations: list[Plantation] = []
    enemy: list[Enemy] = []
    mountains: list[Position] = []
    cells: list[Cell] = []
    construction: list[Construction] = []
    beavers: list[Beaver] = []
    plantation_upgrades: PlantationUpgrades = Field(alias="plantationUpgrades")
    meteo_forecasts: list[MeteoForecast] = Field(default_factory=list, alias="meteoForecasts")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_models.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add cherviak/models.py tests/test_models.py
git commit -m "feat: add pydantic Arena model with camelCase aliases"
```

---

## Task 4: HTTP client with retries

**Files:**
- Create: `cherviak/client.py`

- [ ] **Step 1: Write `cherviak/client.py`**

```python
import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed
from cherviak.config import Config
from cherviak.models import Arena


class GameClient:
    def __init__(self, config: Config, timeout: float = 2.0):
        self._client = httpx.Client(
            base_url=config.base_url,
            headers={"X-Auth-Token": config.token},
            timeout=timeout,
        )

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(0.1),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    def get_arena(self) -> Arena:
        r = self._client.get("/api/arena")
        r.raise_for_status()
        return Arena.model_validate(r.json())

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(0.1),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    def post_command(self, body: dict) -> dict:
        r = self._client.post("/api/command", json=body)
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
```

- [ ] **Step 2: Smoke-test against real server**

Run a quick probe to confirm token works:

```bash
venv/bin/python -c "
from cherviak.config import load_config
from cherviak.client import GameClient
with GameClient(load_config()) as c:
    a = c.get_arena()
    print(f'turn={a.turn_no}, plantations={len(a.plantations)}, hq_pos={[p.position for p in a.plantations if p.is_main]}')
"
```

Expected: prints current turn number and plantation count without exception. If it throws auth error — token in `.env` is wrong; stop and fix before continuing.

- [ ] **Step 3: Commit**

```bash
git add cherviak/client.py
git commit -m "feat: add GameClient with httpx and tenacity retries"
```

---

## Task 5: Brain — geometry helpers and `pick_target` (TDD)

**Files:**
- Create: `tests/test_brain.py`
- Create: `cherviak/brain.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_brain.py`:

```python
from cherviak.brain import (
    cardinal_neighbors,
    chebyshev,
    is_cardinal_neighbor,
    nearest_bonus_distance,
    pick_target,
)
from cherviak.models import Arena


def make_arena(plantations=None, mountains=None, beavers=None,
                construction=None, enemy=None) -> Arena:
    return Arena.model_validate({
        "turnNo": 1,
        "nextTurnIn": 1.0,
        "size": [100, 100],
        "actionRange": 2,
        "plantations": plantations or [],
        "enemy": enemy or [],
        "mountains": mountains or [],
        "cells": [],
        "construction": construction or [],
        "beavers": beavers or [],
        "plantationUpgrades": {
            "points": 0, "intervalTurns": 30, "turnsUntilPoints": 30,
            "maxPoints": 15, "tiers": [],
        },
    })


def make_plant(pos, is_main=False, is_isolated=False, hp=50, immunity=0, pid="p1"):
    return {
        "id": pid, "position": pos, "isMain": is_main,
        "isIsolated": is_isolated, "immunityUntilTurn": immunity, "hp": hp,
    }


def test_chebyshev_distance():
    assert chebyshev([0, 0], [3, 4]) == 4
    assert chebyshev([5, 5], [5, 5]) == 0


def test_cardinal_neighbors_returns_4_orthogonal_cells():
    assert sorted(cardinal_neighbors([10, 10])) == sorted([
        [11, 10], [9, 10], [10, 11], [10, 9],
    ])


def test_is_cardinal_neighbor():
    assert is_cardinal_neighbor([5, 5], [5, 6]) is True
    assert is_cardinal_neighbor([5, 5], [6, 5]) is True
    assert is_cardinal_neighbor([5, 5], [6, 6]) is False  # diagonal
    assert is_cardinal_neighbor([5, 5], [7, 5]) is False  # too far
    assert is_cardinal_neighbor([5, 5], [5, 5]) is False  # same


def test_nearest_bonus_distance():
    assert nearest_bonus_distance([7, 7]) == 0          # on bonus
    assert nearest_bonus_distance([8, 7]) == 1          # one cell away
    assert nearest_bonus_distance([10, 10]) == 6        # nearest is [7,7]: 3+3
    assert nearest_bonus_distance([11, 11]) == 6        # nearest is [14,14]: 3+3
    assert nearest_bonus_distance([14, 14]) == 0        # on bonus


def test_pick_target_chooses_neighbor_closest_to_bonus():
    hq = make_plant([6, 6], is_main=True)
    arena = make_arena(plantations=[hq])
    target = pick_target(arena, arena.plantations[0])
    # candidates: [7,6], [5,6], [6,7], [6,5]
    # distances to [7,7]: [7,6]=1, [5,6]=3, [6,7]=1, [6,5]=3
    # tie between [7,6] and [6,7] — both equally close to bonus
    assert target in ([7, 6], [6, 7])


def test_pick_target_skips_mountains():
    hq = make_plant([7, 6], is_main=True)
    arena = make_arena(plantations=[hq], mountains=[[7, 7]])
    target = pick_target(arena, arena.plantations[0])
    # [7,7] is a bonus cell BUT a mountain — must skip
    assert target != [7, 7]


def test_pick_target_skips_occupied_cells():
    hq = make_plant([7, 6], is_main=True, pid="hq")
    other = make_plant([7, 7], pid="p2")
    arena = make_arena(plantations=[hq, other])
    target = pick_target(arena, arena.plantations[0])
    assert target != [7, 7]


def test_pick_target_skips_construction_in_progress():
    hq = make_plant([7, 6], is_main=True)
    arena = make_arena(
        plantations=[hq],
        construction=[{"position": [7, 7], "progress": 20}],
    )
    target = pick_target(arena, arena.plantations[0])
    assert target != [7, 7]


def test_pick_target_skips_cells_within_2_of_beaver():
    hq = make_plant([7, 6], is_main=True)
    arena = make_arena(
        plantations=[hq],
        beavers=[{"id": "b1", "position": [8, 8], "hp": 100}],
    )
    target = pick_target(arena, arena.plantations[0])
    # [7,7] is within chebyshev radius 2 of [8,8] -> skip
    assert target != [7, 7]


def test_pick_target_returns_none_when_all_blocked():
    hq = make_plant([5, 5], is_main=True)
    arena = make_arena(
        plantations=[hq],
        mountains=[[6, 5], [4, 5], [5, 6], [5, 4]],
    )
    target = pick_target(arena, arena.plantations[0])
    assert target is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_brain.py -v`
Expected: ImportError on `cherviak.brain`.

- [ ] **Step 3: Write `cherviak/brain.py` with helpers and `pick_target`**

```python
from typing import Optional
from cherviak.models import Arena, Plantation


Position = list[int]


def chebyshev(a: Position, b: Position) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def cardinal_neighbors(p: Position) -> list[Position]:
    x, y = p
    return [[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]]


def is_cardinal_neighbor(a: Position, b: Position) -> bool:
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    return (dx == 1 and dy == 0) or (dx == 0 and dy == 1)


def nearest_bonus_distance(p: Position) -> int:
    x, y = p
    bx = round(x / 7) * 7
    by = round(y / 7) * 7
    return abs(x - bx) + abs(y - by)


def pick_target(arena: Arena, hq: Plantation) -> Optional[Position]:
    occupied: set[tuple[int, int]] = set()
    for p in arena.plantations:
        occupied.add(tuple(p.position))
    for e in arena.enemy:
        occupied.add(tuple(e.position))
    for c in arena.construction:
        occupied.add(tuple(c.position))
    mountains = {tuple(m) for m in arena.mountains}
    beaver_positions = [b.position for b in arena.beavers]

    def is_safe(c: Position) -> bool:
        ct = (c[0], c[1])
        if ct in occupied or ct in mountains:
            return False
        for bp in beaver_positions:
            if chebyshev(c, bp) <= 2:
                return False
        return True

    safe = [c for c in cardinal_neighbors(hq.position) if is_safe(c)]
    if not safe:
        return None
    return min(safe, key=nearest_bonus_distance)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_brain.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add cherviak/brain.py tests/test_brain.py
git commit -m "feat(brain): geometry helpers and target picker"
```

---

## Task 6: Brain — `build_commands` (TDD)

**Files:**
- Modify: `tests/test_brain.py`
- Modify: `cherviak/brain.py`

- [ ] **Step 1: Add failing test to `tests/test_brain.py`**

Append to `tests/test_brain.py`:

```python
from cherviak.brain import build_commands


def test_build_commands_includes_plantations_in_action_range():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    near = make_plant([6, 5], pid="near")  # within AR=2 of [7,5]
    far = make_plant([20, 20], pid="far")  # outside AR=2 of [7,5]
    arena = make_arena(plantations=[hq, near, far])
    target = [7, 5]

    commands = build_commands(arena, target)
    builder_positions = sorted([c[0] for c in commands])
    assert builder_positions == sorted([[5, 5], [6, 5]])


def test_build_commands_uses_author_as_relay_to_avoid_penalty():
    hq = make_plant([5, 5], is_main=True)
    arena = make_arena(plantations=[hq])
    target = [6, 5]
    commands = build_commands(arena, target)
    # path is [author, author, target]
    assert commands == [[[5, 5], [5, 5], [6, 5]]]


def test_build_commands_excludes_isolated_plantations():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    isolated = make_plant([6, 5], is_isolated=True, pid="iso")
    arena = make_arena(plantations=[hq, isolated])
    target = [7, 5]
    commands = build_commands(arena, target)
    builders = [c[0] for c in commands]
    assert [6, 5] not in builders


def test_build_commands_empty_when_no_plantations_in_range():
    hq = make_plant([0, 0], is_main=True)
    arena = make_arena(plantations=[hq])
    target = [50, 50]  # way outside AR
    commands = build_commands(arena, target)
    assert commands == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_brain.py -v`
Expected: ImportError on `build_commands`.

- [ ] **Step 3: Add `build_commands` to `cherviak/brain.py`**

Append to `cherviak/brain.py`:

```python
def build_commands(arena: Arena, target: Position) -> list[list[Position]]:
    """Return list of paths [author, author, target] for every controllable
    plantation within action_range of the target."""
    AR = arena.action_range
    paths: list[list[Position]] = []
    for p in arena.plantations:
        if p.is_isolated:
            continue
        if abs(p.position[0] - target[0]) > AR:
            continue
        if abs(p.position[1] - target[1]) > AR:
            continue
        paths.append([p.position, p.position, target])
    return paths
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_brain.py -v`
Expected: 13 passed (9 from Task 5 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add cherviak/brain.py tests/test_brain.py
git commit -m "feat(brain): build_commands for in-range plantations"
```

---

## Task 7: Brain — `check_relocate` (TDD)

**Files:**
- Modify: `tests/test_brain.py`
- Modify: `cherviak/brain.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_brain.py`:

```python
from cherviak.brain import check_relocate


def test_check_relocate_returns_path_when_fresh_neighbor_exists():
    hq = make_plant([5, 5], is_main=True, immunity=0, pid="hq")
    # Freshly built: immunityUntilTurn = current_turn + 3 (turn_no=1 here, so >= 3)
    fresh = make_plant([5, 6], immunity=4, pid="fresh")
    arena = make_arena(plantations=[hq, fresh])

    result = check_relocate(arena)
    assert result == [[5, 5], [5, 6]]


def test_check_relocate_returns_none_when_no_neighbor_is_fresh():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    old_neighbor = make_plant([5, 6], immunity=0, pid="old")
    arena = make_arena(plantations=[hq, old_neighbor])
    assert check_relocate(arena) is None


def test_check_relocate_skips_diagonal_neighbors():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    diag = make_plant([6, 6], immunity=4, pid="diag")
    arena = make_arena(plantations=[hq, diag])
    assert check_relocate(arena) is None


def test_check_relocate_skips_isolated_plantations():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    iso = make_plant([5, 6], immunity=4, is_isolated=True, pid="iso")
    arena = make_arena(plantations=[hq, iso])
    assert check_relocate(arena) is None


def test_check_relocate_returns_none_when_no_hq():
    arena = make_arena(plantations=[])
    assert check_relocate(arena) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_brain.py -v`
Expected: ImportError on `check_relocate`.

- [ ] **Step 3: Add `check_relocate` to `cherviak/brain.py`**

Append to `cherviak/brain.py`:

```python
def check_relocate(arena: Arena) -> Optional[list[Position]]:
    """If a freshly built plantation is cardinally adjacent to HQ,
    return [hq.position, fresh.position] for relocateMain. Else None.

    'Freshly built' = immunityUntilTurn - turn_no >= 2 (built this turn,
    has remaining 3-turn immunity).
    """
    hq = next((p for p in arena.plantations if p.is_main), None)
    if hq is None:
        return None

    for p in arena.plantations:
        if p.is_main or p.is_isolated:
            continue
        if not is_cardinal_neighbor(p.position, hq.position):
            continue
        if p.immunity_until_turn - arena.turn_no < 2:
            continue
        return [hq.position, p.position]
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_brain.py -v`
Expected: 18 passed.

- [ ] **Step 5: Commit**

```bash
git add cherviak/brain.py tests/test_brain.py
git commit -m "feat(brain): check_relocate for HQ chain forward movement"
```

---

## Task 8: Brain — `pick_upgrade` (TDD)

**Files:**
- Modify: `tests/test_brain.py`
- Modify: `cherviak/brain.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_brain.py`:

```python
from cherviak.brain import UPGRADE_ORDER, pick_upgrade


def make_upgrades(points: int, tiers: list[dict]) -> dict:
    return {
        "points": points, "intervalTurns": 30, "turnsUntilPoints": 30,
        "maxPoints": 15, "tiers": tiers,
    }


def test_pick_upgrade_returns_empty_when_no_points():
    arena = Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantationUpgrades": make_upgrades(0, [
            {"name": "repair_power", "current": 0, "max": 3},
        ]),
    })
    assert pick_upgrade(arena) == ""


def test_pick_upgrade_returns_first_in_priority_order():
    arena = Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantationUpgrades": make_upgrades(1, [
            {"name": "max_hp", "current": 0, "max": 5},
            {"name": "repair_power", "current": 0, "max": 3},
        ]),
    })
    assert pick_upgrade(arena) == "repair_power"


def test_pick_upgrade_skips_maxed_tiers():
    arena = Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantationUpgrades": make_upgrades(1, [
            {"name": "repair_power", "current": 3, "max": 3},  # maxed
            {"name": "signal_range", "current": 0, "max": 5},
        ]),
    })
    assert pick_upgrade(arena) == "signal_range"


def test_pick_upgrade_returns_empty_when_all_known_maxed():
    tiers = [{"name": name, "current": 99, "max": 99} for name in UPGRADE_ORDER]
    arena = Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantationUpgrades": make_upgrades(1, tiers),
    })
    assert pick_upgrade(arena) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_brain.py -v`
Expected: ImportError on `UPGRADE_ORDER` / `pick_upgrade`.

- [ ] **Step 3: Add `UPGRADE_ORDER` and `pick_upgrade` to `cherviak/brain.py`**

Append to `cherviak/brain.py`:

```python
UPGRADE_ORDER = [
    "repair_power",
    "signal_range",
    "settlement_limit",
    "decay_mitigation",
    "max_hp",
    "vision_range",
    "earthquake_mitigation",
    "beaver_damage_mitigation",
]


def pick_upgrade(arena: Arena) -> str:
    if arena.plantation_upgrades.points < 1:
        return ""
    by_name = {t.name: t for t in arena.plantation_upgrades.tiers}
    for name in UPGRADE_ORDER:
        tier = by_name.get(name)
        if tier is not None and tier.current < tier.max:
            return name
    return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_brain.py -v`
Expected: 22 passed.

- [ ] **Step 5: Commit**

```bash
git add cherviak/brain.py tests/test_brain.py
git commit -m "feat(brain): pick_upgrade with hardcoded priority order"
```

---

## Task 9: Brain — `decide_turn` composer (TDD)

**Files:**
- Modify: `tests/test_brain.py`
- Modify: `cherviak/brain.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_brain.py`:

```python
from cherviak.brain import decide_turn


def test_decide_turn_returns_none_when_no_hq():
    arena = make_arena(plantations=[])
    assert decide_turn(arena) is None


def test_decide_turn_returns_build_command_for_normal_state():
    hq = make_plant([5, 5], is_main=True)
    arena = make_arena(plantations=[hq])
    body = decide_turn(arena)
    assert body is not None
    assert len(body["command"]) >= 1
    # path goes from HQ to a cardinal neighbor of HQ
    first_cmd = body["command"][0]
    assert first_cmd["path"][0] == [5, 5]


def test_decide_turn_includes_relocate_when_fresh_neighbor_exists():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    fresh = make_plant([5, 6], immunity=4, pid="fresh")
    arena = make_arena(plantations=[hq, fresh])
    body = decide_turn(arena)
    assert body["relocateMain"] == [[5, 5], [5, 6]]


def test_decide_turn_includes_upgrade_when_points_available():
    arena_dict = {
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantations": [make_plant([5, 5], is_main=True)],
        "enemy": [], "mountains": [], "cells": [], "construction": [], "beavers": [],
        "plantationUpgrades": {
            "points": 1, "intervalTurns": 30, "turnsUntilPoints": 30,
            "maxPoints": 15,
            "tiers": [{"name": "repair_power", "current": 0, "max": 3}],
        },
    }
    arena = Arena.model_validate(arena_dict)
    body = decide_turn(arena)
    assert body["plantationUpgrade"] == "repair_power"


def test_decide_turn_returns_none_when_all_blocked_and_no_upgrade():
    hq = make_plant([5, 5], is_main=True)
    arena = make_arena(
        plantations=[hq],
        mountains=[[6, 5], [4, 5], [5, 6], [5, 4]],
    )
    # No build possible, no upgrade points, no fresh neighbor
    assert decide_turn(arena) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_brain.py -v`
Expected: ImportError on `decide_turn`.

- [ ] **Step 3: Add `decide_turn` to `cherviak/brain.py`**

Append to `cherviak/brain.py`:

```python
def decide_turn(arena: Arena) -> Optional[dict]:
    """Compose all decisions into a request body. Returns None if there is
    nothing useful to send (server requires at least one of command/upgrade/
    relocateMain)."""
    hq = next((p for p in arena.plantations if p.is_main), None)
    if hq is None:
        return None

    target = pick_target(arena, hq)
    commands: list[list[Position]] = []
    if target is not None:
        commands = build_commands(arena, target)

    relocate = check_relocate(arena)
    upgrade = pick_upgrade(arena)

    if not commands and not relocate and not upgrade:
        return None

    body: dict = {
        "command": [{"path": c} for c in commands],
        "plantationUpgrade": upgrade,
    }
    if relocate is not None:
        body["relocateMain"] = relocate
    return body
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_brain.py -v`
Expected: 27 passed.

- [ ] **Step 5: Commit**

```bash
git add cherviak/brain.py tests/test_brain.py
git commit -m "feat(brain): decide_turn composer"
```

---

## Task 10: Game loop in `main.py`

**Files:**
- Modify: `main.py` (overwrite the placeholder PyCharm content)

- [ ] **Step 1: Replace `main.py` with the bot loop**

Open `main.py` and replace its entire content with:

```python
import time
from loguru import logger
from cherviak.brain import decide_turn
from cherviak.client import GameClient
from cherviak.config import load_config


def run() -> None:
    config = load_config()
    logger.info(f"Бот стартовал, base_url={config.base_url}")

    last_processed_turn = -1

    with GameClient(config) as client:
        while True:
            try:
                arena = client.get_arena()
            except Exception as e:
                logger.warning(f"Не удалось получить арену: {e}")
                time.sleep(1.0)
                continue

            if arena.turn_no == last_processed_turn:
                # Уже отправили команду в этом ходу — ждём следующий
                time.sleep(min(max(arena.next_turn_in, 0.05), 0.2))
                continue

            last_processed_turn = arena.turn_no
            hq_pos = next((p.position for p in arena.plantations if p.is_main), None)
            logger.info(
                f"Ход {arena.turn_no}: plantations={len(arena.plantations)}, "
                f"hq={hq_pos}, upgrade_points={arena.plantation_upgrades.points}"
            )

            try:
                body = decide_turn(arena)
            except Exception:
                logger.exception(f"Ошибка принятия решения в ходу {arena.turn_no}")
                body = None

            if body is None:
                logger.info(f"Ход {arena.turn_no}: нет действий — пропускаем")
            else:
                try:
                    response = client.post_command(body)
                    errors = response.get("errors") or []
                    if errors:
                        logger.warning(f"Ход {arena.turn_no}: ошибки сервера: {errors}")
                    else:
                        logger.info(f"Ход {arena.turn_no}: команда принята")
                except Exception:
                    logger.exception(f"Ошибка отправки команды в ходу {arena.turn_no}")

            time.sleep(max(arena.next_turn_in, 0.05))


if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Run the bot for ~30 seconds against the test server**

Run: `timeout 30 venv/bin/python main.py 2>&1 | tee /tmp/cherviak_run.log`
Expected: log lines like `Ход N: команда принята` repeating, no exceptions in the tail. If you see auth errors, fix `.env` token.

- [ ] **Step 3: Verify no crashes and HQ is being managed**

Inspect the tail of the log:

```bash
tail -30 /tmp/cherviak_run.log
```

Confirm:
- Multiple `Ход N: ...` lines with increasing N
- No `Traceback` or repeated `WARNING` for empty/invalid commands
- HQ position changes at least once across logged turns (червяк двигается)

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: wire game loop with arena polling and command posting"
```

---

## Task 11: End-to-end checklist verification

**Files:** none (verification only)

- [ ] **Step 1: Confirm full test suite still green**

Run: `venv/bin/pytest`
Expected: 27 passed.

- [ ] **Step 2: Run bot for 2 minutes (≥100 turns at 1s/turn)**

Run: `timeout 120 venv/bin/python main.py 2>&1 | tee /tmp/cherviak_long.log`

- [ ] **Step 3: Verify spec checklist 5.9**

Check the log:

```bash
grep -c "команда принята" /tmp/cherviak_long.log
grep "upgrade_points" /tmp/cherviak_long.log | head -3
grep -i "traceback\|error" /tmp/cherviak_long.log
```

Confirm:
- ≥ 50 «команда принята» lines (bot is acting most turns)
- `upgrade_points` increases over time
- No tracebacks (warnings about empty commands are acceptable)

- [ ] **Step 4: Verify on dashboard**

Open `https://gamethon.datsteam.dev/datssol/stats` in a browser and confirm:
- Your team appears
- Score is non-zero and growing

If both green — MVP is done.

- [ ] **Step 5: Final commit (if any cleanup needed)**

If no changes are needed, skip. Otherwise:

```bash
git add -A
git commit -m "chore: post-verification cleanup"
```

---

## Done

After Task 11, the v1 bot is operational. Next iterations from spec section 5.10:

1. Lateral branches (rear plantation builds sideways instead of helping front)
2. Storm-aware repair scheduling
3. `networkx` graph for accurate isolation detection
4. Beaver hunting (group strikes when ≥4 plantations in AR)
5. Reactive sabotage (finishing 70%+ enemy cells)
6. Async HTTP via `httpx.AsyncClient` (parallel `/arena` + `/logs`)

Each iteration gets its own spec → plan → execute cycle.
