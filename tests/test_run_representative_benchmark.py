from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

import tools.benchmark as benchmark
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


def test_default_output_path_includes_timestamp_and_matchup():
    output_path = representative_benchmark.default_output_path(
        Path("/tmp/rep_bench"),
        bot_a="alpha",
        bot_b="beta",
        now=representative_benchmark.datetime(2026, 4, 3, 20, 0, 0),
    )

    assert output_path == Path("/tmp/rep_bench/20260403_200000_alpha_vs_beta.json")


def test_default_run_replay_dir_includes_timestamp_and_matchup():
    replay_dir = representative_benchmark.default_run_replay_dir(
        Path("/tmp/replays"),
        bot_a="alpha",
        bot_b="beta",
        now=representative_benchmark.datetime(2026, 4, 3, 20, 0, 0),
    )

    assert replay_dir == Path("/tmp/replays/20260403_200000_alpha_vs_beta")


def test_fallback_replay_paths_use_tmp_directory_and_are_unique():
    jobs = representative_benchmark._build_representative_jobs(
        Path("/tmp/alpha"),
        Path("/tmp/beta"),
        selected_maps=[Path("/tmp/maps/default_small1.map26")],
        selected_seeds=[7, 7],
        replay_dir=None,
        swap_seats=True,
        debug=True,
    )

    replay_paths = [Path(job["replay_path"]) for job in jobs]
    assert len(replay_paths) == 4
    assert len(set(replay_paths)) == len(replay_paths)
    assert all(path.parent == representative_benchmark.DEFAULT_TMP_REPLAY_DIR for path in replay_paths)
    assert all(".dist" not in str(path) for path in replay_paths)
    assert all("/.rep_bench/tmp/" in str(path) for path in replay_paths)


def test_run_representative_benchmark_returns_expected_record_count(monkeypatch: pytest.MonkeyPatch):
    _install_fake_resolvers(monkeypatch)

    calls: list[tuple[str, str, str, int, bool]] = []

    def fake_run_local_game(
        bot_a: Path,
        bot_b: Path,
        map_path: Path,
        replay_path: Path,
        seed: int,
        *,
        debug: bool = False,
    ) -> dict[str, object]:
        calls.append((bot_a.name, bot_b.name, map_path.name, seed, debug))
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
    assert all(debug is True for *_prefix, debug in calls)


def test_run_representative_benchmark_respects_no_swap_seats(monkeypatch: pytest.MonkeyPatch):
    _install_fake_resolvers(monkeypatch)
    monkeypatch.setattr(
        representative_benchmark,
        "run_local_game",
        lambda bot_a, bot_b, map_path, replay_path, seed, *, debug=False: {
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


def test_summarize_records_credits_swapped_seat_wins_to_bot_identity():
    summary = benchmark.summarize_records(
        Path("/tmp/alpha"),
        Path("/tmp/beta"),
        [
            {
                "bot_a": "alpha",
                "bot_b": "beta",
                "winner": "A",
                "winner_label": "alpha",
                "turns": 100,
            },
            {
                "bot_a": "beta",
                "bot_b": "alpha",
                "winner": "B",
                "winner_label": "alpha",
                "turns": 140,
            },
            {
                "bot_a": "beta",
                "bot_b": "alpha",
                "winner": "A",
                "winner_label": "beta",
                "turns": 160,
            },
        ],
    )

    assert summary["alpha"]["games"] == 3
    assert summary["beta"]["games"] == 3
    assert summary["alpha"]["wins"] == 2
    assert summary["alpha"]["losses"] == 1
    assert summary["beta"]["wins"] == 1
    assert summary["beta"]["losses"] == 2
    assert summary["alpha"]["average_turns"] == pytest.approx((100 + 140 + 160) / 3)
    assert summary["beta"]["average_turns"] == pytest.approx((100 + 140 + 160) / 3)


def test_run_representative_benchmark_can_disable_debug(monkeypatch: pytest.MonkeyPatch):
    _install_fake_resolvers(monkeypatch)
    observed_debug: list[bool] = []

    def fake_run_local_game(
        bot_a: Path,
        bot_b: Path,
        map_path: Path,
        replay_path: Path,
        seed: int,
        *,
        debug: bool = False,
    ) -> dict[str, object]:
        observed_debug.append(debug)
        return {
            "winner": "A",
            "winner_label": bot_a.name,
            "win_condition": "elimination",
            "turns": 12,
        }

    monkeypatch.setattr(representative_benchmark, "run_local_game", fake_run_local_game)

    representative_benchmark.run_representative_benchmark(
        "alpha",
        "beta",
        maps=["m1.map26"],
        seeds=[1],
        replay_dir=None,
        quiet=True,
        swap_seats=False,
        jobs=1,
        debug=False,
    )

    assert observed_debug == [False]


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
        debug=True,
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
        *,
        debug: bool = False,
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
        "default_output_path",
        lambda base_dir, *, bot_a, bot_b, now=None: base_dir / f"fixed-output_{bot_a}_vs_{bot_b}.json",
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
        lambda base_dir, *, bot_a, bot_b, now=None: base_dir / f"fixed-run_{bot_a}_vs_{bot_b}",
    )
    monkeypatch.setattr(
        representative_benchmark,
        "resolve_bot_path",
        lambda spec: tmp_path / "bots" / spec,
    )
    monkeypatch.setattr(
        representative_benchmark,
        "bot_label",
        lambda path: Path(path).name,
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

    output_path = tmp_path / ".rep_bench" / "fixed-output_alpha_vs_beta.json"
    assert output_path.is_file()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["replay_dir"] == str((tmp_path / ".rep_bench" / "replays" / "fixed-run_alpha_vs_beta").resolve())
    assert observed["kwargs"]["replay_dir"] == tmp_path / ".rep_bench" / "replays" / "fixed-run_alpha_vs_beta"
    assert observed["kwargs"]["debug"] is True

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
    monkeypatch.setattr(
        representative_benchmark,
        "resolve_bot_path",
        lambda spec: tmp_path / "bots" / spec,
    )
    monkeypatch.setattr(
        representative_benchmark,
        "bot_label",
        lambda path: Path(path).name,
    )

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
    assert observed["kwargs"]["debug"] is True
    assert capsys.readouterr().out.strip() == str(custom_output)


def test_main_can_disable_debug(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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
        "resolve_bot_path",
        lambda spec: tmp_path / "bots" / spec,
    )
    monkeypatch.setattr(
        representative_benchmark,
        "bot_label",
        lambda path: Path(path).name,
    )

    def fake_run_representative_benchmark(*args, **kwargs):
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
        ["run_representative_benchmark.py", "alpha", "beta", "--no-debug"],
    )

    representative_benchmark.main()

    assert observed["kwargs"]["debug"] is False


def test_resolve_jobs_auto_caps_worker_count(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(representative_benchmark.os, "cpu_count", lambda: 64)
    assert representative_benchmark.resolve_jobs(None) == representative_benchmark.MAX_WORKERS


@pytest.mark.parametrize("requested_jobs", [0, 9])
def test_resolve_jobs_rejects_invalid_values(requested_jobs: int):
    with pytest.raises(SystemExit, match="--jobs must be between 1 and 8"):
        representative_benchmark.resolve_jobs(requested_jobs)
