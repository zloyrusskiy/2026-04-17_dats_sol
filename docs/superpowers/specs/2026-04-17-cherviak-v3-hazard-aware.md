# Cherviak v3 — Hazard-Aware («Безопасный червяк»)

## Problem

V1/v2 lose HQ in cascading destruction every ~20 turns on prod. Two main causes observed live:
1. HQ relocates onto a fresh plantation that is then hit by a sandstorm or sits next to a beaver — HQ dies, all plantations vanish, 5% score penalty.
2. New builds (`pick_target`) advance червяк into the path of an incoming storm.

`arena.meteo_forecasts` already exposes storms (kind, position, next_position, radius, turns_until) and `arena.beavers` exposes beaver positions. We currently use beaver info only in `pick_target`'s safety check (Chebyshev 2). HQ relocation ignores both.

## Insight

A relocation kills HQ immediately if the target dies on the same turn or is dangerously exposed next turn. A small predicate `is_hazardous(pos, arena)` that checks "in/near a forecasted storm soon" + "within Chebyshev 3 of any beaver" can be applied to:

- `check_relocate` — never relocate into a hazardous cell.
- `pick_target` — extend existing safety check to also avoid hazardous cells.
- `lateral_targets` — same.

Beaver buffer is increased from 2 → 3 specifically for HQ relocation (HQ takes more damage and is the catastrophic loss vector).

## Design

### New brain function: `hazardous_positions(arena, lookahead=3) -> set[tuple[int, int]]`

Walks every storm forecast in `arena.meteo_forecasts`:
- Skip forecasts with no `position` or no `radius` (some kinds, e.g. zone-wide events, may lack these — defensive).
- Compute a path: linear interpolation from `position` toward `next_position` over `lookahead` steps. If `next_position` is missing, treat as stationary.
- For each step `t` in `0..lookahead`, the storm centre is at `lerp(position, next_position, t / max(turns_until, 1))` rounded to int. Mark every cell within Chebyshev `radius` of that centre.

For `lookahead`: 3 turns gives enough buffer for a relocation decision (we relocate now → HQ sits there → storm could hit on turn N+1, N+2, or N+3).

Returns a flat set of `(x, y)` cell coordinates considered dangerous in the lookahead window.

### New brain function: `is_hazardous(pos, hazardous, beavers, beaver_buffer=3) -> bool`

```python
def is_hazardous(pos, hazardous, beavers, beaver_buffer=3):
    if (pos[0], pos[1]) in hazardous:
        return True
    for b in beavers:
        if chebyshev(pos, b.position) <= beaver_buffer:
            return True
    return False
```

### Modified: `check_relocate`

Compute `hazardous = hazardous_positions(arena)` once. Skip a fresh-neighbour candidate if `is_hazardous(candidate, hazardous, arena.beavers)` is true. Existing behaviour (cardinal-adjacent, immunity gate, isolation gate) preserved.

### Modified: `pick_target` and `lateral_targets`

Inside the existing `is_safe(c)` closure (in both functions), add: `if (c[0], c[1]) in hazardous: return False`. Beaver buffer for builds stays at 2 (they're cheap to lose; HQ is not).

### Wiring

- `decide_turn_lateral` (the v2 composer) is the only consumer that actually ships. v1 `decide_turn` may be left unchanged or also benefit — we update it for free since they share `pick_target` / `check_relocate`.
- No new strategy class. The existing `LateralStrategy` benefits transparently.

### Constants

- `STORM_LOOKAHEAD = 3` turns
- `HQ_BEAVER_BUFFER = 3` (relocation only)
- Build-time beaver buffer remains 2 (existing behaviour).

### Non-goals (still deferred)

- Active repair scheduling (we *avoid* hazards; we don't proactively repair what's there)
- networkx isolation
- Beaver hunting (offence)
- Reactive sabotage
- Async client

## Acceptance

- New unit tests cover: storm-cell expansion under stationary and moving storms; HQ relocation skips hazardous fresh neighbour; build target skips hazardous cell; lateral skips hazardous; integration via `decide_turn_lateral`.
- Existing 49 tests still pass.
- Live run shows HQ surviving longer between deaths (eyeball the dashboard / session log; v2 baseline lost HQ ~3 times per 100 turns).

## Out of scope

- Refactoring `pick_target` / `lateral_targets` to share an `is_safe` factory. Could be done, but doubles the change footprint. Prefer two parallel small edits with a TODO if duplication grows.
