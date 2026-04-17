import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    token: str
    base_url: str


def load_config() -> Config:
    load_dotenv()
    token = os.environ.get("DATS_TOKEN", "").strip()
    base_url = os.environ.get("DATS_BASE_URL", "https://games-test.datsteam.dev").strip()
    if not token:
        raise RuntimeError("DATS_TOKEN is not set in .env or environment")
    return Config(token=token, base_url=base_url)
