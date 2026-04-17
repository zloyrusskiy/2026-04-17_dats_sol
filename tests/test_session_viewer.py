import json
from pathlib import Path

from scripts import session_viewer


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_list_sessions_uses_lightweight_summary(tmp_path, monkeypatch):
    older = tmp_path / "session_20260417T100000Z"
    latest = tmp_path / "session_20260417T110000Z"
    older.mkdir()
    latest.mkdir()

    write_json(older / "meta.json", {"startedAt": "2026-04-17T10:00:00Z", "strategy": "passive"})
    write_json(latest / "meta.json", {"startedAt": "2026-04-17T11:00:00Z", "strategy": "lateral"})
    write_jsonl(older / "turns.jsonl", [{"kind": "turn", "turnNo": 3}, {"kind": "turn", "turnNo": 4}])
    write_jsonl(latest / "turns.jsonl", [{"kind": "turn", "turnNo": 10}, {"kind": "turn", "turnNo": 11}])
    write_jsonl(older / "logs.jsonl", [{"message": "a"}])
    write_jsonl(latest / "logs.jsonl", [{"message": "a"}, {"message": "b"}])

    monkeypatch.setattr(
        session_viewer,
        "load_session",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("full session load is not expected")),
    )

    sessions = session_viewer.list_sessions(tmp_path)

    assert [session["id"] for session in sessions] == [latest.name, older.name]
    assert sessions[0]["frameCount"] == 2
    assert sessions[0]["firstTurn"] == 10
    assert sessions[0]["lastTurn"] == 11
    assert sessions[0]["logCount"] == 2


def test_load_session_exposes_html_legend_separately(tmp_path):
    session_dir = tmp_path / "session_20260417T120000Z"
    session_dir.mkdir()

    write_json(session_dir / "meta.json", {"strategy": "passive"})
    write_jsonl(
        session_dir / "turns.jsonl",
        [
            {
                "kind": "turn",
                "turnNo": 7,
                "arena": {
                    "turnNo": 7,
                    "size": [3, 2],
                    "actionRange": 4,
                    "mountains": [],
                    "cells": [{"position": [0, 0], "terraformationProgress": 55}],
                    "construction": [],
                    "enemy": [],
                    "plantations": [{"position": [1, 1], "isMain": True, "hp": 99}],
                    "beavers": [],
                },
                "capturedAt": "2026-04-17T12:00:00Z",
                "nextTurnIn": 1,
                "decision": {"kind": "wait"},
                "response": {"ok": True},
            }
        ],
    )
    write_jsonl(session_dir / "logs.jsonl", [])

    payload = session_viewer.load_session(str(session_dir), cell_size=18)

    frame = payload["frames"][0]
    assert frame["legend"]["title"] == "DatsSol Session Frame"
    assert frame["legend"]["stats"][0] == "turn: 7"
    assert any(item["label"] == "your HQ" for item in frame["legend"]["items"])
    assert 'width="138"' in frame["svg"]
