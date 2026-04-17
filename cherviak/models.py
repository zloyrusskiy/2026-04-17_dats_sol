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
    turns_until: Optional[int] = Field(default=None, alias="turnsUntil")
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
