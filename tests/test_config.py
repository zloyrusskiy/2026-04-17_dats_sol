import pytest

from cherviak import config as config_module
from cherviak.config import load_config


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("DATS_TOKEN", "DATS_BASE_URL", "LATENCY_AVG", "POLL_INTERVAL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(config_module, "load_dotenv", lambda *args, **kwargs: False)


def test_load_config_uses_defaults_for_latency_and_poll(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATS_TOKEN", "tok")

    config = load_config()

    assert config.token == "tok"
    assert config.base_url == "https://games-test.datsteam.dev"
    assert config.latency_avg == 0.1
    assert config.poll_interval == 0.5


def test_load_config_reads_latency_avg_and_poll_interval_from_env(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATS_TOKEN", "tok")
    monkeypatch.setenv("LATENCY_AVG", "0.25")
    monkeypatch.setenv("POLL_INTERVAL", "0.3")

    config = load_config()

    assert config.latency_avg == 0.25
    assert config.poll_interval == 0.3


def test_load_config_rejects_non_numeric_latency(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATS_TOKEN", "tok")
    monkeypatch.setenv("LATENCY_AVG", "abc")

    with pytest.raises(RuntimeError, match="LATENCY_AVG"):
        load_config()


def test_load_config_rejects_non_positive_poll_interval(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATS_TOKEN", "tok")
    monkeypatch.setenv("POLL_INTERVAL", "0")

    with pytest.raises(RuntimeError, match="POLL_INTERVAL"):
        load_config()


def test_load_config_requires_token(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(RuntimeError, match="DATS_TOKEN"):
        load_config()
