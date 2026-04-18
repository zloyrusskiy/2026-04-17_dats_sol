import httpx
import pytest

from cherviak.client import GameClient, HTTP2_ENABLED, KEEPALIVE_LIMITS
from cherviak.config import Config

def test_timestamp_uses_milliseconds_without_timezone():
    client = GameClient(Config(token="token", base_url="https://example.test"))

    timestamp = client._timestamp()

    assert timestamp.count(".") == 1
    assert len(timestamp.split(".")[1]) == 3
    assert timestamp.count(":") == 2


def test_get_arena_logs_turn_number(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch):
    client = GameClient(
        Config(token="token", base_url="https://example.test"),
        log_requests=True,
    )
    monkeypatch.setattr(
        client._client,
        "request",
        lambda method, path, json=None: httpx.Response(
            200,
            json={
                "turnNo": 533,
                "nextTurnIn": 1.0,
                "size": [100, 100],
                "actionRange": 2,
                "plantations": [],
                "enemy": [],
                "mountains": [],
                "cells": [],
                "construction": [],
                "beavers": [],
                "plantationUpgrades": {
                    "points": 0,
                    "intervalTurns": 30,
                    "turnsUntilPoints": 30,
                    "maxPoints": 15,
                    "tiers": [],
                },
                "meteoForecasts": [],
            },
            request=httpx.Request(method, f"https://example.test{path}"),
        ),
    )

    with caplog.at_level("DEBUG", logger="cherviak.client"):
        arena = client.get_arena()

    assert arena.turn_no == 533
    assert "GET /api/arena status=200" in caplog.text
    assert "http=HTTP/1.1" in caplog.text
    assert "turnNo=533" in caplog.text
    assert '== GET /api/arena raw={"turnNo":533,"nextTurnIn":1.0' in caplog.text


def test_client_enables_keepalive_and_http2(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def close(self):
            return None

    monkeypatch.setattr("cherviak.client.httpx.Client", DummyClient)

    client = GameClient(Config(token="token", base_url="https://example.test"))

    assert captured["http2"] is HTTP2_ENABLED
    assert captured["limits"] == KEEPALIVE_LIMITS
    client.close()
