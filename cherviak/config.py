import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    token: str
    base_url: str
    latency_avg: float = 0.1
    poll_interval: float = 0.5


def _parse_positive_float(name: str, raw: str, allow_zero: bool) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a float (seconds), got {raw!r}") from exc
    if allow_zero:
        if value < 0:
            raise RuntimeError(f"{name} must be non-negative, got {value}")
    else:
        if value <= 0:
            raise RuntimeError(f"{name} must be positive, got {value}")
    return value


def load_config() -> Config:
    load_dotenv()
    token = os.environ.get("DATS_TOKEN", "").strip()
    base_url = os.environ.get("DATS_BASE_URL", "https://games-test.datsteam.dev").strip()
    latency_avg_raw = os.environ.get("LATENCY_AVG", "0.1").strip()
    poll_interval_raw = os.environ.get("POLL_INTERVAL", "0.5").strip()
    if not token:
        raise RuntimeError("DATS_TOKEN is not set in .env or environment")
    latency_avg = _parse_positive_float("LATENCY_AVG", latency_avg_raw, allow_zero=True)
    poll_interval = _parse_positive_float("POLL_INTERVAL", poll_interval_raw, allow_zero=False)
    return Config(
        token=token,
        base_url=base_url,
        latency_avg=latency_avg,
        poll_interval=poll_interval,
    )
