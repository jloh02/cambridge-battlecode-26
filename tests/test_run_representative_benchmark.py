from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

import tools.run_representative_benchmark as representative_benchmark


def _install_fake_resolvers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        representative_benchmark,
        "resolve_bot_path",
        lambda spec: representative_benchmark.ROOT / "bots" / spec,
    )
    monkeypatch.setattr(
        representative_benchmark,
        "resolve_map_path",
        lambda spec: representative_benchmark.ROOT / "maps" / spec,
    )


def test_default_output_path_uses_rep_bench_root():
    assert representative_benchmark.DEFAULT_OUTPUT_PATH == (
        representative_benchmark.ROOT / ".rep_bench" / "representative_benchmark.json"
    )
    assert ".dist" not in str(representative_benchmark.DEFAULT_OUTPUT_PATH)
    assert "/.rep_bench/" in str(representative_benchmark.DEFAULT_OUTPUT_PATH)


def test_fallback_replay_paths_use_tmp_directory_and_are_unique():
    jobs = representative_benchmark._build_representative_jobs(
        Path("/tmp/alpha"),
        Path("/tmp/beta"),
        selected_maps=[Path("/tmp/maps/default_small1.map26")],
        selected_seeds=[7, 7],
        replay_dir=None,
        swap_seats=True,
    )

    replay_paths = [Path(job["replay_path"]) for job in jobs]
    assert len(replay_paths) == 4
    assert len(set(replay_paths)) == len(replay_paths)
    assert all(path.parent == representative_benchmark.DEFAULT_TMP_REPLAY_DIR for path in replay_paths)
    assert all(".dist" not in str(path) for path in replay_paths)
    assert all("/.rep_bench/tmp/" in str(path) for path in replay_paths)


def test_run_representative_benchmark_returns_expected_record_count(monkeypatch: pytest.MonkeyPatch):
    _install_fake_resolvers(monkeypatch)

    calls: list[tuple[str, str, str, int]] = []

    def fake_run_local_game(
        bot_a: Path,
        bot_b: Path,
        map_path: Path,
        replay_path: Path,
        seed: int,
    ) -> dict[str, object]:
        calls.append((bot_a.name, bot_b.name, map_path.name, seed))
        return {
            "winner": "A",
            "winner_label": bot_a.name,
            "win_condition": "elimination",
            "turns": 42,
        }

    monkeypatch.setattr(representative_benchmark, "run_local_game", fake_run_local_game)

    payload = representative_benchmark.run_representative_benchmark(
        "alpha",
        "beta",
        maps=["m1.map26", "m2.map26"],
        seeds=[1, 2],
        replay_dir=representative_benchmark.ROOT / ".rep_bench" / "replays" / "suite",
        quiet=True,
        jobs=1,
    )

    assert len(payload["records"]) == 8
    assert len(calls) == 8
    assert payload["maps"] == ["m1.map26", "m2.map26"]
    assert payload["seeds"] == [1, 2]
    assert all("replay_path" in record for record in payload["records"])


def test_run_representative_benchmark_respects_no_swap_seats(monkeypatch: pytest.MonkeyPatch):
    _install_fake_resolvers(monkeypatch)
    monkeypatch.setattr(
        representative_benchmark,
        "run_local_game",
        lambda bot_a, bot_b, map_path, replay_path, seed: {
            "winner": "A",
            "winner_label": bot_a.name,
            "win_condition": "elimination",
            "turns": 12,
        },
    )

    payload = representative_benchmark.run_representative_benchmark(
        "alpha",
        "beta",
        maps=["m1.map26", "m2.map26"],
        seeds=[1, 2],
        replay_dir=None,
        quiet=True,
        swap_seats=False,
        jobs=1,
    )

    assert payload["swap_seats"] is False
    assert len(payload["records"]) == 4
    assert all(record["bot_a"] == "alpha" for record in payload["records"])
    assert all(record["bot_b"] == "beta" for record in payload["records"])
    assert all("replay_path" not in record for record in payload["records"])


def test_concurrent_execution_preserves_deterministic_record_order(monkeypatch: pytest.MonkeyPatch):
    _install_fake_resolvers(monkeypatch)

    expected_jobs = representative_benchmark._build_representative_jobs(
        representative_benchmark.ROOT / "bots" / "alpha",
        representative_benchmark.ROOT / "bots" / "beta",
        selected_maps=[
            representative_benchmark.ROOT / "maps" / "m1.map26",
            representative_benchmark.ROOT / "maps" / "m2.map26",
        ],
        selected_seeds=[1, 2],
        replay_dir=None,
        swap_seats=True,
    )
    expected_order = [
        (
            Path(job["bot_a_path"]).name,
            Path(job["bot_b_path"]).name,
            Path(job["map_path"]).name,
            int(job["seed"]),
        )
        for job in expected_jobs
    ]

    observed_threads: list[int] = []
    lock = threading.Lock()

    def fake_run_local_game(
        bot_a: Path,
        bot_b: Path,
        map_path: Path,
        replay_path: Path,
        seed: int,
    ) -> dict[str, object]:
        time.sleep(0.01 if seed == 2 else 0.03)
        with lock:
            observed_threads.append(threading.get_ident())
        return {
            "winner": "A",
            "winner_label": bot_a.name,
            "win_condition": "elimination",
            "turns": 99 - seed,
        }

    monkeypatch.setattr(representative_benchmark, "run_local_game", fake_run_local_game)

    payload = representative_benchmark.run_representative_benchmark(
        "alpha",
        "beta",
        maps=["m1.map26", "m2.map26"],
        seeds=[1, 2],
        replay_dir=None,
        quiet=True,
        jobs=4,
    )

    observed_order = [
        (record["bot_a"], record["bot_b"], record["map_name"], int(record["seed"]))
        for record in payload["records"]
    ]

    assert observed_order == expected_order
    assert len(set(observed_threads)) > 1


def test_main_writes_to_rep_bench_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    observed: dict[str, object] = {}

    monkeypatch.setattr(representative_benchmark, "ROOT", tmp_path)
    monkeypatch.setattr(
        representative_benchmark,
        "REP_BENCH_DIR",
        tmp_path / ".rep_bench",
    )
    monkeypatch.setattr(
        representative_benchmark,
        "DEFAULT_OUTPUT_PATH",
        tmp_path / ".rep_bench" / "representative_benchmark.json",
    )
    monkeypatch.setattr(
        representative_benchmark,
        "DEFAULT_REPLAY_BASE_DIR",
        tmp_path / ".rep_bench" / "replays",
    )
    monkeypatch.setattr(
        representative_benchmark,
        "DEFAULT_TMP_REPLAY_DIR",
        tmp_path / ".rep_bench" / "tmp",
    )
    monkeypatch.setattr(
        representative_benchmark,
        "default_run_replay_dir",
        lambda base_dir, now=None: base_dir / "fixed-run",
    )

    def fake_run_representative_benchmark(*args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs
        return {
            "bot_a": "alpha",
            "bot_b": "beta",
            "maps": ["default_small1.map26"],
            "seeds": [1, 7],
            "swap_seats": True,
            "records": [],
            "summary": {"alpha": {}, "beta": {}},
        }

    monkeypatch.setattr(representative_benchmark, "run_representative_benchmark", fake_run_representative_benchmark)
    monkeypatch.setattr(sys, "argv", ["run_representative_benchmark.py", "alpha", "beta"])

    representative_benchmark.main()

    output_path = tmp_path / ".rep_bench" / "representative_benchmark.json"
    assert output_path.is_file()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["replay_dir"] == str((tmp_path / ".rep_bench" / "replays" / "fixed-run").resolve())
    assert observed["kwargs"]["replay_dir"] == tmp_path / ".rep_bench" / "replays" / "fixed-run"

    printed_path = capsys.readouterr().out.strip()
    assert printed_path == str(output_path)
    assert ".dist" not in printed_path


def test_main_respects_explicit_output_and_replay_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    observed: dict[str, object] = {}
    custom_output = tmp_path / "custom" / "out.json"
    custom_replay_dir = tmp_path / "custom" / "replays"

    monkeypatch.setattr(representative_benchmark, "ROOT", tmp_path)

    def fake_run_representative_benchmark(*args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs
        return {
            "bot_a": "alpha",
            "bot_b": "beta",
            "maps": ["default_small1.map26"],
            "seeds": [1],
            "swap_seats": True,
            "records": [],
            "summary": {"alpha": {}, "beta": {}},
        }

    monkeypatch.setattr(representative_benchmark, "run_representative_benchmark", fake_run_representative_benchmark)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_representative_benchmark.py",
            "alpha",
            "beta",
            "--output",
            str(custom_output),
            "--replay-dir",
            str(custom_replay_dir),
        ],
    )

    representative_benchmark.main()

    assert custom_output.is_file()
    payload = json.loads(custom_output.read_text(encoding="utf-8"))
    assert payload["replay_dir"] == str(custom_replay_dir.resolve())
    assert observed["kwargs"]["replay_dir"] == custom_replay_dir
    assert capsys.readouterr().out.strip() == str(custom_output)


def test_resolve_jobs_auto_caps_worker_count(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(representative_benchmark.os, "cpu_count", lambda: 64)
    assert representative_benchmark.resolve_jobs(None) == representative_benchmark.MAX_WORKERS


@pytest.mark.parametrize("requested_jobs", [0, 9])
def test_resolve_jobs_rejects_invalid_values(requested_jobs: int):
    with pytest.raises(SystemExit, match="--jobs must be between 1 and 8"):
        representative_benchmark.resolve_jobs(requested_jobs)
