import httpx
import pytest

from cherviak.client import GameClient, _is_retryable_http_error
from cherviak.config import Config


def make_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/api/logs")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_retryable_for_transient_network_errors():
    request = httpx.Request("GET", "https://example.test/api/arena")
    exc = httpx.ReadTimeout("boom", request=request)
    assert _is_retryable_http_error(exc) is True


def test_retryable_for_server_errors():
    assert _is_retryable_http_error(make_status_error(503)) is True


def test_not_retryable_for_rate_limit():
    assert _is_retryable_http_error(make_status_error(429)) is False


def test_not_retryable_for_other_client_errors():
    assert _is_retryable_http_error(make_status_error(400)) is False


def test_request_spacing_respects_min_request_interval(monkeypatch: pytest.MonkeyPatch):
    monotonic_values = iter([0.0, 0.1, 0.35])
    sleep_calls: list[float] = []

    monkeypatch.setattr("cherviak.client.time.monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr("cherviak.client.time.sleep", lambda seconds: sleep_calls.append(seconds))

    client = GameClient(
        Config(token="token", base_url="https://example.test"),
        min_request_interval=0.35,
    )
    monkeypatch.setattr(
        client._client,
        "request",
        lambda method, path, json=None: httpx.Response(
            200,
            request=httpx.Request(method, f"https://example.test{path}"),
        ),
    )

    client._request("GET", "/api/arena")
    client._request("GET", "/api/logs")

    assert sleep_calls == [pytest.approx(0.25)]


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
    assert "turnNo=533" in caplog.text
