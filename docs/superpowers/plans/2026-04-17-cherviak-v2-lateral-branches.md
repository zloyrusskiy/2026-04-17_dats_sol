# Cherviak v2 «Рыба-червяк» Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add lateral-branch building so plantations near cell-completion grow perpendicular ribs, keeping more plantations alive simultaneously.

**Architecture:** Add pure functions `lateral_targets` and `decide_turn_lateral` to `cherviak/brain.py`. Add `LateralStrategy` in `cherviak/strategies/lateral.py`. Register in `scripts/run_session.py`. Do NOT touch v1 `MvpStrategy` or its `decide_turn`.

**Tech Stack:** Python 3, pydantic v2, pytest. No new dependencies.

---

### Task 1: forward_direction helper

**Files:**
- Modify: `cherviak/brain.py`
- Test: `tests/test_brain.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_brain.py`:

```python
from cherviak.brain import forward_direction


def test_forward_direction_pure_x():
    assert forward_direction([5, 5], [8, 5]) == (1, 0)
    assert forward_direction([5, 5], [2, 5]) == (-1, 0)


def test_forward_direction_pure_y():
    assert forward_direction([5, 5], [5, 9]) == (0, 1)
    assert forward_direction([5, 5], [5, 1]) == (0, -1)


def test_forward_direction_diagonal_returns_x_component():
    # diagonal червяк — prefer X axis as the "forward" we treat as primary
    assert forward_direction([5, 5], [8, 8]) == (1, 0)
    assert forward_direction([5, 5], [2, 2]) == (-1, 0)


def test_forward_direction_same_position_returns_zero():
    assert forward_direction([5, 5], [5, 5]) == (0, 0)
```

- [ ] **Step 2: Run, verify fails**

`venv/bin/python -m pytest tests/test_brain.py -k forward_direction -v` → ImportError or NameError.

- [ ] **Step 3: Implement**

Add to `cherviak/brain.py` (above `pick_target`):

```python
def forward_direction(hq: Position, p: Position) -> tuple[int, int]:
    """Unit-vector direction from hq to p. For diagonal, return X-axis component."""
    dx = p[0] - hq[0]
    dy = p[1] - hq[1]
    if dx == 0 and dy == 0:
        return (0, 0)
    sx = (dx > 0) - (dx < 0)
    sy = (dy > 0) - (dy < 0)
    if sx != 0:
        return (sx, 0)
    return (0, sy)
```

- [ ] **Step 4: Run, verify pass**

`venv/bin/python -m pytest tests/test_brain.py -k forward_direction -v` → 4 passed.

- [ ] **Step 5: Commit**

```bash
git add cherviak/brain.py tests/test_brain.py
git commit -m "feat(brain): forward_direction helper for lateral-branch logic"
```

---

### Task 2: lateral_targets — threshold gate + perpendicular pick

**Files:**
- Modify: `cherviak/brain.py`
- Test: `tests/test_brain.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_brain.py`:

```python
from cherviak.brain import LATERAL_THRESHOLD, lateral_targets


def make_cell(pos, progress=0, ttd=80):
    return {"position": pos, "terraformationProgress": progress,
            "turnsUntilDegradation": ttd}


def test_lateral_targets_skips_below_threshold():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    rib_parent = make_plant([7, 5], pid="r1")
    arena = make_arena(
        plantations=[hq, rib_parent],
    )
    # inject cell with low progress
    arena.cells.append(__import__("cherviak.models", fromlist=["Cell"]).Cell.model_validate(
        make_cell([7, 5], progress=LATERAL_THRESHOLD - 1)))
    assert lateral_targets(arena) == []


def test_lateral_targets_picks_perpendicular_when_threshold_reached():
    from cherviak.models import Cell
    hq = make_plant([5, 5], is_main=True, pid="hq")
    rib_parent = make_plant([7, 5], pid="r1")  # forward = (+1, 0) so perpendicular = Y axis
    arena = make_arena(plantations=[hq, rib_parent])
    arena.cells.append(Cell.model_validate(make_cell([7, 5], progress=LATERAL_THRESHOLD)))

    result = lateral_targets(arena)
    assert len(result) == 1
    builder, target = result[0]
    assert builder.id == "r1"
    assert target in ([7, 6], [7, 4])  # perpendicular to forward X


def test_lateral_targets_skips_hq():
    from cherviak.models import Cell
    hq = make_plant([5, 5], is_main=True, pid="hq")
    arena = make_arena(plantations=[hq])
    arena.cells.append(Cell.model_validate(make_cell([5, 5], progress=99)))
    assert lateral_targets(arena) == []


def test_lateral_targets_skips_isolated():
    from cherviak.models import Cell
    hq = make_plant([5, 5], is_main=True, pid="hq")
    iso = make_plant([7, 5], is_isolated=True, pid="iso")
    arena = make_arena(plantations=[hq, iso])
    arena.cells.append(Cell.model_validate(make_cell([7, 5], progress=99)))
    assert lateral_targets(arena) == []


def test_lateral_targets_filters_unsafe_candidates():
    from cherviak.models import Cell
    hq = make_plant([5, 5], is_main=True, pid="hq")
    rib_parent = make_plant([7, 5], pid="r1")
    # block one perpendicular with mountain, the other with another plantation
    blocker = make_plant([7, 4], pid="b")
    arena = make_arena(
        plantations=[hq, rib_parent, blocker],
        mountains=[[7, 6]],
    )
    arena.cells.append(Cell.model_validate(make_cell([7, 5], progress=80)))
    assert lateral_targets(arena) == []


def test_lateral_targets_skips_when_no_cell_data():
    hq = make_plant([5, 5], is_main=True, pid="hq")
    rib_parent = make_plant([7, 5], pid="r1")
    arena = make_arena(plantations=[hq, rib_parent])
    # no cell entry for [7,5]
    assert lateral_targets(arena) == []


def test_lateral_targets_picks_bonus_neighbor_when_two_safe():
    from cherviak.models import Cell
    # forward axis Y so perpendiculars are X. [7, 6] is closer to bonus [7,7].
    hq = make_plant([7, 4], is_main=True, pid="hq")
    rib_parent = make_plant([7, 6], pid="r1")  # forward (0, +1), perpendiculars X
    arena = make_arena(plantations=[hq, rib_parent])
    arena.cells.append(Cell.model_validate(make_cell([7, 6], progress=80)))
    result = lateral_targets(arena)
    assert len(result) == 1
    _, target = result[0]
    # candidates: [8,6] dist to nearest bonus [7,7]=1+1=2; [6,6] dist to [7,7]=1+1=2 — tie
    # both equally good — accept either
    assert target in ([8, 6], [6, 6])
```

- [ ] **Step 2: Run, verify fails**

`venv/bin/python -m pytest tests/test_brain.py -k lateral_targets -v` → ImportError.

- [ ] **Step 3: Implement**

Add to `cherviak/brain.py` (after `build_commands`, before `check_relocate`):

```python
LATERAL_THRESHOLD = 70


def lateral_targets(arena: Arena) -> list[tuple[Plantation, Position]]:
    """For each plantation whose cell is near completion, suggest a perpendicular
    side-build to keep a survivor after the cell completes."""
    hq = next((p for p in arena.plantations if p.is_main), None)
    if hq is None:
        return []

    cell_by_pos = {tuple(c.position): c for c in arena.cells}

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
        if c[0] < 0 or c[1] < 0 or c[0] >= arena.size[0] or c[1] >= arena.size[1]:
            return False
        ct = (c[0], c[1])
        if ct in occupied or ct in mountains:
            return False
        for bp in beaver_positions:
            if chebyshev(c, bp) <= 2:
                return False
        return True

    out: list[tuple[Plantation, Position]] = []
    for p in arena.plantations:
        if p.is_main or p.is_isolated:
            continue
        cell = cell_by_pos.get(tuple(p.position))
        if cell is None:
            continue
        if cell.terraformation_progress < LATERAL_THRESHOLD:
            continue
        fx, fy = forward_direction(hq.position, p.position)
        if fx == 0 and fy == 0:
            continue
        if fx != 0:
            cands = [[p.position[0], p.position[1] + 1], [p.position[0], p.position[1] - 1]]
        else:
            cands = [[p.position[0] + 1, p.position[1]], [p.position[0] - 1, p.position[1]]]
        safe = [c for c in cands if is_safe(c)]
        if not safe:
            continue
        out.append((p, min(safe, key=nearest_bonus_distance)))
    return out
```

Also add the import at top of `cherviak/brain.py` if not present:

```python
from cherviak.models import Arena, Plantation
```

(`Plantation` may not yet be imported — verify and add.)

- [ ] **Step 4: Run, verify pass**

`venv/bin/python -m pytest tests/test_brain.py -k lateral_targets -v` → 7 passed.

- [ ] **Step 5: Commit**

```bash
git add cherviak/brain.py tests/test_brain.py
git commit -m "feat(brain): lateral_targets picks perpendicular ribs at terraform>=70%"
```

---

### Task 3: decide_turn_lateral composer

**Files:**
- Modify: `cherviak/brain.py`
- Test: `tests/test_brain.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_brain.py`:

```python
from cherviak.brain import decide_turn_lateral


def test_decide_turn_lateral_includes_lateral_command():
    from cherviak.models import Cell
    hq = make_plant([5, 5], is_main=True, pid="hq")
    rib_parent = make_plant([7, 5], pid="r1")
    arena = make_arena(plantations=[hq, rib_parent])
    arena.cells.append(Cell.model_validate(make_cell([7, 5], progress=80)))

    body = decide_turn_lateral(arena)
    assert body is not None
    paths = [c["path"] for c in body["command"]]
    # at least one path is from rib_parent to a perpendicular neighbor
    lateral_paths = [
        p for p in paths
        if p[0] == [7, 5] and p[2] in ([7, 6], [7, 4])
    ]
    assert len(lateral_paths) >= 1


def test_decide_turn_lateral_does_not_double_command_same_builder():
    # rib_parent is in AR of forward target AND has lateral. Only one command.
    from cherviak.models import Cell
    hq = make_plant([5, 5], is_main=True, pid="hq")
    rib_parent = make_plant([6, 5], pid="r1")  # forward (+1,0), in AR of [7,5]
    arena = make_arena(plantations=[hq, rib_parent])
    arena.cells.append(Cell.model_validate(make_cell([6, 5], progress=80)))

    body = decide_turn_lateral(arena)
    assert body is not None
    builders = [c["path"][0] for c in body["command"]]
    # rib_parent appears exactly once across all commands
    assert builders.count([6, 5]) == 1


def test_decide_turn_lateral_returns_none_when_nothing_to_do():
    hq = make_plant([5, 5], is_main=True)
    arena = make_arena(
        plantations=[hq],
        mountains=[[6, 5], [4, 5], [5, 6], [5, 4]],
    )
    assert decide_turn_lateral(arena) is None
```

- [ ] **Step 2: Run, verify fails**

`venv/bin/python -m pytest tests/test_brain.py -k decide_turn_lateral -v`

- [ ] **Step 3: Implement**

Add to `cherviak/brain.py` (after `decide_turn`):

```python
def decide_turn_lateral(arena: Arena) -> Optional[dict]:
    """Composer that extends decide_turn with lateral-branch builds."""
    hq = next((p for p in arena.plantations if p.is_main), None)
    if hq is None:
        return None

    target = pick_target(arena, hq)
    commands: list[list[Position]] = []
    if target is not None:
        commands = build_commands(arena, target)

    used_builders: set[tuple[int, int]] = {tuple(c[0]) for c in commands}
    used_targets: set[tuple[int, int]] = {tuple(c[2]) for c in commands}

    for builder, lat_target in lateral_targets(arena):
        bp = (builder.position[0], builder.position[1])
        tp = (lat_target[0], lat_target[1])
        if bp in used_builders:
            continue
        if tp in used_targets:
            continue
        commands.append([builder.position, builder.position, lat_target])
        used_builders.add(bp)
        used_targets.add(tp)

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

- [ ] **Step 4: Run, verify pass**

`venv/bin/python -m pytest tests/test_brain.py -v` → all pass (35 prior + 14 new = 49).

- [ ] **Step 5: Commit**

```bash
git add cherviak/brain.py tests/test_brain.py
git commit -m "feat(brain): decide_turn_lateral composes forward + lateral builds"
```

---

### Task 4: LateralStrategy + registry

**Files:**
- Create: `cherviak/strategies/lateral.py`
- Modify: `scripts/run_session.py`

- [ ] **Step 1: Read existing pattern**

Read `cherviak/strategies/mvp.py` and `scripts/run_session.py` to mirror exactly.

- [ ] **Step 2: Create strategy file**

Write `cherviak/strategies/lateral.py`:

```python
from __future__ import annotations

from typing import Any

from cherviak.brain import decide_turn_lateral
from cherviak.models import Arena
from cherviak.strategies.base import StrategyState


class LateralStrategy:
    """V2: червяк + perpendicular ribs near cell completion («рыба-червяк»)."""

    name = "lateral"

    def __init__(self) -> None:
        self.state = StrategyState()

    def on_round_started(self) -> None:
        self.state = StrategyState(round_started=True)

    def decide_turn(self, arena: Arena) -> dict[str, Any] | None:
        self.state.seen_turns += 1
        self.state.last_turn_no = arena.turn_no
        return decide_turn_lateral(arena)

    def on_turn_result(
        self,
        arena: Arena,
        command: dict[str, Any] | None,
        response: dict[str, Any] | None,
    ) -> None:
        self.state.last_turn_no = arena.turn_no
        self.state.notes["last_command_sent"] = bool(command)
        self.state.notes["last_response_code"] = None if response is None else response.get("code")
        if isinstance(response, dict):
            errors = response.get("errors")
            if errors:
                self.state.notes["last_errors"] = errors
```

- [ ] **Step 3: Register in run_session.py**

Find the `STRATEGIES` registry block in `scripts/run_session.py` and add LateralStrategy:

```python
from cherviak.strategies.lateral import LateralStrategy

STRATEGIES = {
    PassiveStrategy.name: PassiveStrategy,
    MvpStrategy.name: MvpStrategy,
    LateralStrategy.name: LateralStrategy,
}
```

(Match existing style — only add lines, do not reformat.)

- [ ] **Step 4: Smoke check**

`venv/bin/python scripts/run_session.py` → should print available strategies including `lateral`.

`venv/bin/python -c "from cherviak.strategies.lateral import LateralStrategy; s = LateralStrategy(); print(s.name)"` → prints `lateral`.

- [ ] **Step 5: Commit**

```bash
git add cherviak/strategies/lateral.py scripts/run_session.py
git commit -m "feat(strategies): register lateral (рыба-червяк) strategy"
```

---

### Task 5: Update CLAUDE.md / AGENTS.md notes

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Append note**

In the `## Strategies` section of `AGENTS.md`, add a bullet under the existing list:

```
- `lateral` strategy («рыба-червяк»): extends `mvp` with perpendicular side-branches built when a plantation's cell reaches LATERAL_THRESHOLD (70%) terraformation. Keeps more plantations alive after cell completion. Logic in `cherviak/brain.py:decide_turn_lateral`.
```

- [ ] **Step 2: Commit**

```bash
git add AGENTS.md
git commit -m "docs: note lateral strategy in AGENTS.md"
```

---

### Final verification

- [ ] Run full suite: `venv/bin/python -m pytest -v` → all green.
- [ ] Run `venv/bin/python scripts/run_session.py --strategy lateral` for ~60s and verify no traceback (skip if no token).
- [ ] Report: tests passed, commits, anything anomalous.
