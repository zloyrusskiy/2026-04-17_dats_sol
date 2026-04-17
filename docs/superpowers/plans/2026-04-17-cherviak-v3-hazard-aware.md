# Cherviak v3 «Безопасный червяк» Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make HQ relocation and target picking hazard-aware so storms and beavers stop killing HQ in cascades.

**Architecture:** Add pure functions `hazardous_positions` and `is_hazardous` to `cherviak/brain.py`. Extend safety closures inside `pick_target`, `lateral_targets`, and `check_relocate`. No new strategy class — `LateralStrategy` benefits transparently.

**Tech Stack:** Python 3, pydantic v2, pytest. No new dependencies.

---

### Task 1: hazardous_positions — stationary storm expansion

**Files:**
- Modify: `cherviak/brain.py`
- Test: `tests/test_brain.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_brain.py`:

```python
from cherviak.brain import STORM_LOOKAHEAD, hazardous_positions


def make_meteo(kind="sandstorm", position=None, next_position=None,
               radius=None, turns_until=None, forming=False, mid="m1"):
    out = {"kind": kind, "id": mid, "forming": forming}
    if position is not None:
        out["position"] = position
    if next_position is not None:
        out["nextPosition"] = next_position
    if radius is not None:
        out["radius"] = radius
    if turns_until is not None:
        out["turnsUntil"] = turns_until
    return out


def make_arena_with_meteo(meteo_list):
    return Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantations": [], "enemy": [], "mountains": [], "cells": [],
        "construction": [], "beavers": [],
        "plantationUpgrades": {
            "points": 0, "intervalTurns": 30, "turnsUntilPoints": 30,
            "maxPoints": 15, "tiers": [],
        },
        "meteoForecasts": meteo_list,
    })


def test_hazardous_positions_stationary_storm_marks_chebyshev_radius():
    arena = make_arena_with_meteo([
        make_meteo(position=[10, 10], radius=1, turns_until=1),
    ])
    haz = hazardous_positions(arena)
    # 3x3 around [10,10]
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            assert (10 + dx, 10 + dy) in haz
    assert (12, 10) not in haz
    assert (10, 12) not in haz


def test_hazardous_positions_skips_meteo_without_position_or_radius():
    arena = make_arena_with_meteo([
        make_meteo(kind="solar_flare", position=None, radius=None, turns_until=2),
        make_meteo(position=[5, 5], radius=None, turns_until=1),
        make_meteo(position=None, radius=2, turns_until=1),
    ])
    assert hazardous_positions(arena) == set()


def test_hazardous_positions_empty_when_no_meteo():
    arena = make_arena_with_meteo([])
    assert hazardous_positions(arena) == set()
```

- [ ] **Step 2: Run, verify fails**

`venv/bin/python -m pytest tests/test_brain.py -k hazardous_positions -v` → ImportError.

- [ ] **Step 3: Implement (stationary case only — moving comes in Task 2)**

Add to `cherviak/brain.py` (after `nearest_bonus_distance`):

```python
STORM_LOOKAHEAD = 3


def hazardous_positions(arena: Arena, lookahead: int = STORM_LOOKAHEAD) -> set[tuple[int, int]]:
    """Cells expected to be inside a storm in the next `lookahead` turns."""
    haz: set[tuple[int, int]] = set()
    for f in arena.meteo_forecasts:
        if f.position is None or f.radius is None:
            continue
        cx, cy = f.position
        r = f.radius
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                haz.add((cx + dx, cy + dy))
    return haz
```

- [ ] **Step 4: Run, verify pass**

`venv/bin/python -m pytest tests/test_brain.py -k hazardous_positions -v` → 3 passed.

- [ ] **Step 5: Commit**

```bash
git add cherviak/brain.py tests/test_brain.py
git commit -m "feat(brain): hazardous_positions for stationary storms"
```

---

### Task 2: hazardous_positions — moving storm interpolation

**Files:**
- Modify: `cherviak/brain.py`
- Test: `tests/test_brain.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_brain.py`:

```python
def test_hazardous_positions_moving_storm_marks_path_cells():
    # storm at [10,10], moving to [13,10], turns_until=3, radius=0
    # lookahead=3: centres at t=0 [10,10], t=1 [11,10], t=2 [12,10], t=3 [13,10]
    arena = make_arena_with_meteo([
        make_meteo(position=[10, 10], next_position=[13, 10], radius=0, turns_until=3),
    ])
    haz = hazardous_positions(arena, lookahead=3)
    assert (10, 10) in haz
    assert (11, 10) in haz
    assert (12, 10) in haz
    assert (13, 10) in haz
    assert (14, 10) not in haz


def test_hazardous_positions_moving_storm_with_radius_marks_swept_band():
    arena = make_arena_with_meteo([
        make_meteo(position=[5, 5], next_position=[7, 5], radius=1, turns_until=2),
    ])
    haz = hazardous_positions(arena, lookahead=2)
    # at t=0: 3x3 around [5,5]; at t=1: around [6,5]; at t=2: around [7,5]
    for cx in (5, 6, 7):
        for dy in (-1, 0, 1):
            assert (cx, 5 + dy) in haz
    assert (8, 5) in haz  # right edge of t=2 radius
    assert (4, 5) in haz  # left edge of t=0 radius
    assert (9, 5) not in haz
```

- [ ] **Step 2: Run, verify fails**

`venv/bin/python -m pytest tests/test_brain.py -k "hazardous_positions_moving" -v` → AssertionError.

- [ ] **Step 3: Implement**

Replace the `hazardous_positions` body in `cherviak/brain.py` with:

```python
def hazardous_positions(arena: Arena, lookahead: int = STORM_LOOKAHEAD) -> set[tuple[int, int]]:
    """Cells expected to be inside a storm in the next `lookahead` turns."""
    haz: set[tuple[int, int]] = set()
    for f in arena.meteo_forecasts:
        if f.position is None or f.radius is None:
            continue
        x0, y0 = f.position
        if f.next_position is not None and f.turns_until and f.turns_until > 0:
            x1, y1 = f.next_position
            steps = min(lookahead, f.turns_until)
        else:
            x1, y1 = x0, y0
            steps = lookahead
        denom = max(steps, 1)
        for t in range(steps + 1):
            cx = x0 + round((x1 - x0) * t / denom)
            cy = y0 + round((y1 - y0) * t / denom)
            r = f.radius
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    haz.add((cx + dx, cy + dy))
    return haz
```

- [ ] **Step 4: Run, verify pass**

`venv/bin/python -m pytest tests/test_brain.py -k hazardous_positions -v` → 5 passed.

- [ ] **Step 5: Commit**

```bash
git add cherviak/brain.py tests/test_brain.py
git commit -m "feat(brain): hazardous_positions interpolates moving storm path"
```

---

### Task 3: is_hazardous predicate

**Files:**
- Modify: `cherviak/brain.py`
- Test: `tests/test_brain.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_brain.py`:

```python
from cherviak.brain import is_hazardous
from cherviak.models import Beaver


def test_is_hazardous_true_when_in_hazard_set():
    assert is_hazardous([5, 5], {(5, 5)}, []) is True


def test_is_hazardous_true_when_within_beaver_buffer():
    b = Beaver.model_validate({"id": "b1", "position": [10, 10], "hp": 100})
    assert is_hazardous([12, 11], set(), [b], beaver_buffer=3) is True
    assert is_hazardous([13, 13], set(), [b], beaver_buffer=3) is True


def test_is_hazardous_false_outside_buffer_and_hazards():
    b = Beaver.model_validate({"id": "b1", "position": [0, 0], "hp": 100})
    assert is_hazardous([10, 10], {(99, 99)}, [b], beaver_buffer=3) is False
```

- [ ] **Step 2: Run, verify fails**

`venv/bin/python -m pytest tests/test_brain.py -k is_hazardous -v`

- [ ] **Step 3: Implement**

Add to `cherviak/brain.py` (after `hazardous_positions`):

```python
def is_hazardous(
    pos: Position,
    hazardous: set[tuple[int, int]],
    beavers,
    beaver_buffer: int = 3,
) -> bool:
    if (pos[0], pos[1]) in hazardous:
        return True
    for b in beavers:
        if chebyshev(pos, b.position) <= beaver_buffer:
            return True
    return False
```

- [ ] **Step 4: Run, verify pass**

`venv/bin/python -m pytest tests/test_brain.py -k is_hazardous -v` → 3 passed.

- [ ] **Step 5: Commit**

```bash
git add cherviak/brain.py tests/test_brain.py
git commit -m "feat(brain): is_hazardous predicate (storm cells + beaver buffer)"
```

---

### Task 4: check_relocate — skip hazardous targets

**Files:**
- Modify: `cherviak/brain.py`
- Test: `tests/test_brain.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_brain.py`:

```python
def test_check_relocate_skips_fresh_neighbor_in_storm():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    fresh = make_plant([5, 6], immunity=4, pid="fresh")
    arena = Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantations": [hq, fresh], "enemy": [], "mountains": [], "cells": [],
        "construction": [], "beavers": [],
        "plantationUpgrades": {
            "points": 0, "intervalTurns": 30, "turnsUntilPoints": 30,
            "maxPoints": 15, "tiers": [],
        },
        "meteoForecasts": [
            {"kind": "sandstorm", "id": "m1", "forming": False,
             "position": [5, 6], "radius": 0, "turnsUntil": 1},
        ],
    })
    assert check_relocate(arena) is None


def test_check_relocate_skips_fresh_neighbor_near_beaver():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    fresh = make_plant([5, 6], immunity=4, pid="fresh")
    arena = Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantations": [hq, fresh], "enemy": [], "mountains": [], "cells": [],
        "construction": [],
        "beavers": [{"id": "b1", "position": [7, 7], "hp": 100}],  # cheb([5,6],[7,7])=2 ≤ 3
        "plantationUpgrades": {
            "points": 0, "intervalTurns": 30, "turnsUntilPoints": 30,
            "maxPoints": 15, "tiers": [],
        },
    })
    assert check_relocate(arena) is None
```

- [ ] **Step 2: Run, verify fails**

`venv/bin/python -m pytest tests/test_brain.py -k "check_relocate_skips_fresh_neighbor_in_storm or check_relocate_skips_fresh_neighbor_near_beaver" -v`

- [ ] **Step 3: Modify check_relocate**

In `cherviak/brain.py`, locate `check_relocate` and modify it to compute hazardous and skip hazardous candidates. Edit the existing function body so that, after computing `hq` and before the loop, it computes `haz = hazardous_positions(arena)`. Inside the loop, after the cardinal-neighbour and immunity checks, add:

```python
        if is_hazardous(p.position, haz, arena.beavers, beaver_buffer=3):
            continue
```

The full updated function should look like:

```python
def check_relocate(arena: Arena) -> Optional[list[Position]]:
    hq = next((p for p in arena.plantations if p.is_main), None)
    if hq is None:
        return None

    haz = hazardous_positions(arena)
    for p in arena.plantations:
        if p.is_main or p.is_isolated:
            continue
        if not is_cardinal_neighbor(p.position, hq.position):
            continue
        if p.immunity_until_turn - arena.turn_no < 2:
            continue
        if is_hazardous(p.position, haz, arena.beavers, beaver_buffer=3):
            continue
        return [hq.position, p.position]
    return None
```

(Preserve the existing docstring at the top of the function.)

- [ ] **Step 4: Run, verify pass + no regressions**

`venv/bin/python -m pytest tests/test_brain.py -v 2>&1 | tail -5` → all green (existing relocate tests still pass; new ones pass).

- [ ] **Step 5: Commit**

```bash
git add cherviak/brain.py tests/test_brain.py
git commit -m "feat(brain): check_relocate avoids hazardous fresh neighbors"
```

---

### Task 5: pick_target and lateral_targets — skip hazardous cells

**Files:**
- Modify: `cherviak/brain.py`
- Test: `tests/test_brain.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_brain.py`:

```python
def test_pick_target_skips_cells_in_storm_path():
    hq = make_plant([7, 6], is_main=True)
    arena = Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantations": [hq], "enemy": [], "mountains": [], "cells": [],
        "construction": [], "beavers": [],
        "plantationUpgrades": {
            "points": 0, "intervalTurns": 30, "turnsUntilPoints": 30,
            "maxPoints": 15, "tiers": [],
        },
        "meteoForecasts": [
            {"kind": "sandstorm", "id": "m1", "forming": False,
             "position": [7, 7], "radius": 0, "turnsUntil": 1},
        ],
    })
    target = pick_target(arena, arena.plantations[0])
    assert target != [7, 7]


def test_lateral_targets_skips_hazardous_perpendicular():
    from cherviak.models import Cell
    hq = make_plant([5, 5], is_main=True, pid="hq")
    rib_parent = make_plant([7, 5], pid="r1")
    arena = Arena.model_validate({
        "turnNo": 1, "nextTurnIn": 1.0, "size": [100, 100], "actionRange": 2,
        "plantations": [hq, rib_parent], "enemy": [], "mountains": [],
        "cells": [], "construction": [], "beavers": [],
        "plantationUpgrades": {
            "points": 0, "intervalTurns": 30, "turnsUntilPoints": 30,
            "maxPoints": 15, "tiers": [],
        },
        "meteoForecasts": [
            # cover both [7,6] and [7,4]
            {"kind": "sandstorm", "id": "m1", "forming": False,
             "position": [7, 5], "radius": 1, "turnsUntil": 1},
        ],
    })
    arena.cells.append(Cell.model_validate(make_cell([7, 5], progress=80)))
    assert lateral_targets(arena) == []
```

- [ ] **Step 2: Run, verify fails**

`venv/bin/python -m pytest tests/test_brain.py -k "pick_target_skips_cells_in_storm_path or lateral_targets_skips_hazardous_perpendicular" -v`

- [ ] **Step 3: Modify pick_target and lateral_targets**

In both `pick_target` and `lateral_targets` in `cherviak/brain.py`, compute hazardous and extend the `is_safe` closure.

For `pick_target`, near the top (before the closure), add:

```python
    haz = hazardous_positions(arena)
```

Inside the `is_safe(c)` closure, after the existing mountains/occupied check, add:

```python
        if (c[0], c[1]) in haz:
            return False
```

(Note: beaver buffer for builds stays at 2 — the existing check is preserved. Hazardous storm cells get added on top.)

Repeat the same edit in `lateral_targets`.

- [ ] **Step 4: Run, verify pass + no regressions**

`venv/bin/python -m pytest -v 2>&1 | tail -5` → all green (49 prior + ~13 new = ~62).

- [ ] **Step 5: Commit**

```bash
git add cherviak/brain.py tests/test_brain.py
git commit -m "feat(brain): pick_target/lateral_targets skip storm cells"
```

---

### Final verification

- [ ] Run full suite: `venv/bin/python -m pytest -v` → all green.
- [ ] Print summary: total commits made + final test count + any deviations.
