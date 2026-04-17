from __future__ import annotations

from typing import Any

from cherviak.brain import decide_turn
from cherviak.models import Arena
from cherviak.strategies.base import StrategyState


class MvpStrategy:
    """Baseline strategy: chain-build plantations from HQ, relocate HQ forward, spend upgrade points."""

    name = "mvp"

    def __init__(self) -> None:
        self.state = StrategyState()

    def on_round_started(self) -> None:
        self.state = StrategyState(round_started=True)

    def decide_turn(self, arena: Arena) -> dict[str, Any] | None:
        self.state.seen_turns += 1
        self.state.last_turn_no = arena.turn_no
        return decide_turn(arena)

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
