from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StrategyState:
    round_started: bool = False
    seen_turns: int = 0
    last_turn_no: int | None = None
    notes: dict[str, Any] = field(default_factory=dict)
