# Cherviak v2 — Lateral Branches («Рыба-червяк»)

## Problem

V1 «Червяк» builds plantations in a forward-moving chain anchored on HQ. When a plantation's cell hits 100% terraformation, the plantation disappears. In a linear chain this destroys the chain's tail, isolating downstream nodes — effective live plantations stays at ~2-3 instead of growing. Live test on prod (106 turns) confirmed: HQ-relocate cycle survives but plantations are continuously lost; few simultaneous earners.

## Insight

When a plantation is *about to vanish* (terraformation_progress ≥ threshold), instead of helping the front (which it can't anyway — it's leaving), it should spend its last action on building a **perpendicular** neighbor. That perpendicular plantation is anchored to the *next* plantation in the chain (still alive after tail leaves) and survives, growing into a side branch.

Result: chain looks like a fish skeleton — central spine moves forward, ribs spread sideways and continue scoring after the spine cell completes. 5-8x more concurrent earners.

## Design

### New brain function: `lateral_targets(arena) -> list[tuple[Plantation, Position]]`

For each non-isolated plantation `p`:
- Find the cell at `p.position` (`arena.cells`). Skip if no cell (defensive).
- If `cell.terraformation_progress < LATERAL_THRESHOLD` (= 70), skip.
- Compute the «forward» direction = unit vector from HQ to `p` (sign of dx, sign of dy). If `p` is HQ itself, skip.
- Pick a perpendicular neighbor:
  - If forward is along X, candidates are `[p.x, p.y+1]` and `[p.x, p.y-1]`.
  - If forward is along Y, candidates are `[p.x+1, p.y]` and `[p.x-1, p.y]`.
  - If forward is diagonal (rare — HQ moved diagonally over time), prefer pure-X perpendicular.
- Filter candidates with the same safety predicate as `pick_target` (in bounds, not occupied, not mountain, not within Chebyshev 2 of any beaver).
- Among surviving candidates, pick the one closest to a bonus cell (reuse `nearest_bonus_distance`).
- If any survives: emit `(p, chosen_position)`.

### Wiring into `decide_turn`

After computing forward `target` and `commands` from `build_commands(arena, target)`:

1. Compute `laterals = lateral_targets(arena)`.
2. For each `(builder, lat_target)` in `laterals`:
   - Skip if `lat_target` collides with any existing forward `target` or already-queued lateral target (no double-build on same cell).
   - Skip if builder is already issuing a forward command (avoid two commands from same plantation in one turn — server may reject, and relay penalty).
   - Append `[builder.position, builder.position, lat_target]` to commands.
3. Rest unchanged (relocate, upgrade).

### Constants

- `LATERAL_THRESHOLD = 70` — terraform % at which we start growing ribs. Tunable; rationale: at 10%/turn equivalent rate, gives ~3 turns of rib-build immunity before parent dies.

### Non-goals (still deferred)

- Storm-aware repair scheduling
- networkx isolation graph
- Beaver hunting
- Reactive sabotage
- Async client

## Acceptance

- New unit tests cover: threshold gate, perpendicular direction selection, safety filter, bonus tiebreak, no-double-build, no-double-command-from-same-builder, integration via `decide_turn`.
- Existing 35 tests still pass.
- Live run for ≥ 100 turns shows simultaneous live plantations growing past 5 (vs v1 cap ~3) without HQ death cascades.

## Integration with existing strategy registry

Add new strategy class `LateralStrategy` in `cherviak/strategies/lateral.py` (mirrors `MvpStrategy` but calls a `decide_turn_lateral` composer). Register in `scripts/run_session.py`. **Do not modify `mvp.py` or `passive.py`** — keep v1 baseline intact for comparison.
