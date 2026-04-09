from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.benchmark as benchmark


def test_run_local_game_appends_tle_flag_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    monkeypatch.setattr(benchmark, "resolve_cambc_binary", lambda: Path("/tmp/cambc"))

    def fake_run(command, *, capture_output, text, check, env):
        observed["command"] = command
        return SimpleNamespace(
            returncode=0,
            stdout="Winner: alpha (Core destroyed, turn 123)\n",
            stderr="",
        )

    monkeypatch.setattr(benchmark.subprocess, "run", fake_run)

    result = benchmark.run_local_game(
        Path("/tmp/alpha"),
        Path("/tmp/beta"),
        Path("/tmp/maps/a.map26"),
        Path("/tmp/replay.replay26"),
        7,
        tle_ms=2,
    )

    assert result["winner"] == "A"
    assert observed["command"] == [
        "/tmp/cambc",
        "run",
        "/tmp/alpha",
        "/tmp/beta",
        "/tmp/maps/a.map26",
        "--seed",
        "7",
        "--replay",
        "/tmp/replay.replay26",
        "--tle",
        "2",
    ]


def test_run_local_game_rejects_negative_tle_ms() -> None:
    with pytest.raises(ValueError, match="tle_ms must be non-negative"):
        benchmark.run_local_game(
            Path("/tmp/alpha"),
            Path("/tmp/beta"),
            Path("/tmp/maps/a.map26"),
            Path("/tmp/replay.replay26"),
            7,
            tle_ms=-1,
        )
