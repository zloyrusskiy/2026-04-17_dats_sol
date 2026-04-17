# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

DatsSol hackathon game bot — a Python client for a turn-based strategy game where players terraform a planet by building plantation networks while competing with opponents. Full game rules are in `docs/specs/dats_sol_spec.md`, API spec in `docs/specs/openapi.yml`.

## Commands

```bash
source venv/bin/activate    # activate virtualenv
python main.py              # run the bot
```

Python virtualenv is at `venv/`. Always use `venv/bin/python` (not system Python) when running scripts or installing packages.

No build system, test framework, or linter configured yet.

## Game API

- **Test server:** `https://games-test.datsteam.dev`
- **Prod server:** `https://games.datsteam.dev`
- Auth header: `X-Auth-Token: <token>`
- `GET /api/arena` — world state (plantations, enemies, map, meteo, upgrades)
- `POST /api/command` — send actions (build/repair/sabotage/attack + upgrades + relocate HQ)
- `GET /api/logs` — player event logs

Coordinates are `[x, y]` arrays. Command paths are `[[author], [relay], [target]]`.

## Key Game Mechanics (affects bot design)

- **Turn duration:** 1 second — bot must fetch state, decide, and submit within this window
- **Round:** 600 turns, progress resets between rounds, points accumulate across rounds
- **HQ (ЦУ):** losing it destroys all plantations + 5% score penalty; protect at all costs
- **Adjacency:** plantations must form unbroken cardinal (non-diagonal) chain from HQ to be controllable
- **Relay penalty:** each additional command routed through the same relay plantation loses 1 effectiveness (CS/RS/SE/BE), down to 0
- **Radii are squares:** |ΔX| ≤ R and |ΔY| ≤ R (Chebyshev distance), not circles
- **Bonus cells:** where both X and Y are divisible by 7 yield 1.5x points (1500 max vs 1000)
- **Cell completion:** plantation disappears when cell reaches 100% terraform; cell degrades after 80 turns at 10%/turn
- **Construction:** building HP threshold is always 50 (not affected by MHP upgrades); new plantation gets 3-turn immunity
- **Plant limit overflow:** building beyond limit auto-destroys oldest plantation (can destroy HQ!)
- **Beavers:** 100 HP, regen 5/turn, deal 15 HP damage in radius 2, killing one yields 10x cell points

## Server Processing Order (per turn)

1. Upgrades → 2. Repair/Build → 3. Sabotage → 4. Beaver attack (player→beaver) → 5. HQ relocate → 6. Beaver attack (beaver→player) → 7. Lost plantation degradation → 8. Idle construction damage → 9. Terraform + scoring → 10. Respawn → 11. Natural disasters

## Language

Game documentation and code comments are in Russian. Bot code can be in English or Russian.
