from __future__ import annotations

from typing import Any

from cherviak.models import Arena
from cherviak.strategies.base import StrategyState


class PassiveStrategy:
    """Stub strategy used to record arena/logs without sending actions.

    The runner can call this class today to build history and visualization,
    then swap in a real strategy later without changing the session loop API.
    """

    name = "passive"

    def __init__(self) -> None:
        self.state = StrategyState()

    def on_round_started(self) -> None:
        self.state = StrategyState(round_started=True)

    def decide_turn(self, arena: Arena) -> dict[str, Any] | None:
        self.state.seen_turns += 1
        self.state.last_turn_no = arena.turn_no
        return None

    def on_turn_result(
        self,
        arena: Arena,
        command: dict[str, Any] | None,
        response: dict[str, Any] | None,
    ) -> None:
        self.state.last_turn_no = arena.turn_no
        self.state.notes["last_command_sent"] = bool(command)
        self.state.notes["last_response_code"] = None if response is None else response.get("code")
