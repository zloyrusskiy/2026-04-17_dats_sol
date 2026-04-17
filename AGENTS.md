# AGENTS.md

This file provides guidance for Claude Code and similar coding agents working in this repository.

`CLAUDE.md` must be a symbolic link to `AGENTS.md`. These filenames refer to the same guideline document and must never diverge.

## Project

DatsSol hackathon game bot — a Python client for a turn-based strategy game where players terraform a planet by building plantation networks while competing with opponents. Full game rules are in `docs/specs/dats_sol_spec.md`, API spec in `docs/specs/openapi.yml`.

## Commands

```bash
source venv/bin/activate
venv/bin/python main.py
venv/bin/python scripts/run_session.py --strategy passive
```

Python virtualenv is at `venv/`. Always use `venv/bin/python` when running scripts or installing packages.

## Strategies

- Strategy implementations live in `cherviak/strategies/`.
- Each strategy should expose a stable `name` field and the same runner-facing methods used by `PassiveStrategy`: `on_round_started()`, `decide_turn(arena)`, and `on_turn_result(arena, command, response)`.
- Put each strategy in its own module under `cherviak/strategies/`. Shared primitives such as base state/dataclasses should also live in that package.
- To make a strategy available in `scripts/run_session.py`, import the class there and add it to the `STRATEGIES` registry:

```python
from cherviak.strategies import MyStrategy

STRATEGIES = {
    PassiveStrategy.name: PassiveStrategy,
    MyStrategy.name: MyStrategy,
}
```

- `scripts/run_session.py` requires `--strategy`. If it is omitted, the script prints the list of available strategies from `STRATEGIES`.
- When adding a new strategy, keep the registry key equal to `StrategyClass.name` so CLI names stay consistent with metadata written to session artifacts.
- `lateral` strategy («рыба-червяк»): chain-builds plantations from HQ with perpendicular side-branches built when a plantation's cell reaches `LATERAL_THRESHOLD` (70%) terraformation. Keeps more plantations alive after cell completion. Logic in `cherviak/brain.py:decide_turn_lateral`.

## Notes

- Turn duration is 1 second, so strategy code should stay lightweight.
- Losing HQ destroys all plantations and causes a score penalty, so any aggressive strategy still needs HQ safety checks.
- Radii are square/Chebyshev-based, not circular.
