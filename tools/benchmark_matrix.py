"""Run a candidate bot against one or more opponents and summarize the results."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import os
import random
import sys
import traceback
from pathlib import Path
from statistics import pstdev
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.analyze_replay import EXEC_TIME_PRESSURE_THRESHOLDS_US, analyze_replay_path
from tools.benchmark import (
    available_bot_names,
    bot_label,
    default_maps,
    resolve_map_path,
    resolve_bot_path,
    run_local_game,
)


DEFAULT_GAMES_PER_OPPONENT = 32
MAX_WORKERS = os.cpu_count() or 8
DEFAULT_MAX_OPPONENTS = 5
PROMOTION_WIN_RATE_THRESHOLD = 0.8
PROMOTION_TIEQ_AVG_THRESHOLD = 150000
PROMOTION_TIEQ_WORST_THRESHOLD = 0
DEFAULT_SCHEDULE_SEED = 1
EARLY_WIN_TIEQ_BONUS = 100000
ROUND_LIMIT = 2000
MAX_PROGRESS_UPDATES = 32


EventEmitter = Callable[[str], None]
EXEC_PRESSURE_LABELS = tuple(label for _, label in EXEC_TIME_PRESSURE_THRESHOLDS_US)


def _builder_pressure_count_field(label: str) -> str:
    return f"builder_turns_over_{label}"


def _candidate_builder_pressure_count_field(label: str) -> str:
    return f"candidate_{_builder_pressure_count_field(label)}"


def _candidate_builder_pressure_rate_field(label: str) -> str:
    return f"{_candidate_builder_pressure_count_field(label)}_rate"


def _format_builder_pressure_rates(stats: dict[str, Any]) -> str:
    rates = [
        f"{float(stats.get(_candidate_builder_pressure_rate_field(label), 0.0)):.1%}"
        for label in EXEC_PRESSURE_LABELS
    ]
    return "/".join(rates)


def resolve_jobs(requested_jobs: int | None) -> int:
    if requested_jobs is None:
        return max(1, min(MAX_WORKERS, os.cpu_count() or 1))
    if requested_jobs < 1 or requested_jobs > MAX_WORKERS:
        raise SystemExit(f"--jobs must be between 1 and {MAX_WORKERS}")
    return requested_jobs


def _dedupe_ordered(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _safe_token(text: str) -> str:
    token = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text)
    while "__" in token:
        token = token.replace("__", "_")
    return token.strip("_") or "x"


def default_output_path(candidate: str, opponents: list[str]) -> Path:
    """Generate a readable report file when the caller skips `--output`."""
    reports_dir = ROOT / ".dist" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    opponent_label = "field" if not opponents else "-".join(_safe_token(name) for name in opponents[:3])
    return reports_dir / f"{_safe_token(candidate)}_vs_{opponent_label}_matrix.json"


def default_tournament_output_path(candidate: str, opponents: list[str]) -> Path:
    reports_dir = ROOT / ".dist" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    opponent_label = "field" if not opponents else "-".join(_safe_token(name) for name in opponents[:3])
    return reports_dir / f"{_safe_token(candidate)}_vs_{opponent_label}_tournament.json"


def _new_bucket() -> dict[str, Any]:
    bucket = {
        "games": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "turns_sum": 0,
        "win_rate": 0.0,
        "average_turns": 0.0,
        "candidate_tieq_sum": 0,
        "candidate_tieq_avg": 0.0,
        "candidate_tieq_worst": None,
        "candidate_delivered_titanium": 0,
        "candidate_delivered_refined_axionite": 0,
        "candidate_mined_titanium": 0,
        "candidate_mined_axionite": 0,
        "candidate_harvesters_alive": 0,
        "candidate_stored_titanium": 0,
        "candidate_stored_axionite": 0,
        "candidate_builder_turns": 0,
        "candidate_tled_turns": 0,
        "candidate_small_loop_games": 0,
        "win_condition_counts": {},
    }
    for label in EXEC_PRESSURE_LABELS:
        bucket[_candidate_builder_pressure_count_field(label)] = 0
        bucket[_candidate_builder_pressure_rate_field(label)] = 0.0
    return bucket


def _candidate_won(record: dict[str, Any]) -> bool:
    return (
        (record["candidate_team"] == "TEAM_A" and record["winner"] == "A")
        or (record["candidate_team"] == "TEAM_B" and record["winner"] == "B")
    )


def _extract_metrics(analysis: dict[str, Any]) -> dict[str, Any]:
    delivered = analysis.get("delivered_resources", {})
    final_resources = analysis.get("final_resources", {})
    alive_by_kind = analysis.get("alive_by_kind", {})
    metrics: dict[str, Any] = {
        "delivered_titanium": int(delivered.get("titanium", 0)),
        "delivered_refined_axionite": int(delivered.get("refined_axionite", 0)),
        "mined_titanium": int(final_resources.get("titanium_collected", 0)),
        "mined_axionite": int(final_resources.get("axionite_collected", 0)),
        "stored_titanium": int(final_resources.get("titanium", 0)),
        "stored_axionite": int(final_resources.get("axionite", 0)),
        "harvesters_alive": int(alive_by_kind.get("harvester", 0)),
        "builder_turns": int(analysis.get("builder_turns", 0)),
        "tled_turns": int(analysis.get("tled_turns", 0)),
        "builder_max_small_loop_streak": int(analysis.get("builder_max_small_loop_streak", 0)),
    }
    for label in EXEC_PRESSURE_LABELS:
        count_field = _builder_pressure_count_field(label)
        metrics[count_field] = int(analysis.get(count_field, 0))
        metrics[f"{count_field}_rate"] = float(analysis.get(f"{count_field}_rate", 0.0))
    return metrics


def _tieq(metrics: dict[str, int], *, won_early: bool) -> int:
    value = metrics["delivered_titanium"] + (4 * metrics["delivered_refined_axionite"])
    if won_early:
        value += EARLY_WIN_TIEQ_BONUS
    return value


def _run_matrix_job(job: dict[str, Any]) -> dict[str, Any]:
    bot_a_path = Path(job["bot_a_path"])
    bot_b_path = Path(job["bot_b_path"])
    map_path = Path(job["map_path"])
    replay_path = Path(job["replay_path"])
    replay_path.parent.mkdir(parents=True, exist_ok=True)

    result = run_local_game(
        bot_a_path,
        bot_b_path,
        map_path,
        replay_path,
        int(job["seed"]),
        tle_ms=job.get("tle_ms"),
    )

    analysis = analyze_replay_path(replay_path, map_name=map_path.stem)
    candidate_team = "TEAM_A" if job["candidate"] == job["bot_a"] else "TEAM_B"
    opponent_team = "TEAM_B" if candidate_team == "TEAM_A" else "TEAM_A"

    candidate_analysis = analysis["teams"][candidate_team]
    opponent_analysis = analysis["teams"][opponent_team]
    candidate_metrics = _extract_metrics(candidate_analysis)
    opponent_metrics = _extract_metrics(opponent_analysis)
    candidate_won = (
        (candidate_team == "TEAM_A" and result["winner"] == "A")
        or (candidate_team == "TEAM_B" and result["winner"] == "B")
    )
    opponent_won = result["winner"] in {"A", "B"} and not candidate_won

    analysis_output = Path(job["analysis_output"])
    analysis_output.parent.mkdir(parents=True, exist_ok=True)
    analysis_output.write_text(
        json.dumps({"games": [analysis]}, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return {
        "candidate": job["candidate"],
        "opponent": job["opponent"],
        "bot_a": job["bot_a"],
        "bot_b": job["bot_b"],
        "candidate_team": candidate_team,
        "map_name": map_path.name,
        "seed": int(job["seed"]),
        "replay_path": str(replay_path.relative_to(ROOT)) if replay_path.is_relative_to(ROOT) else str(replay_path),
        "winner": result["winner"],
        "win_condition": result["win_condition"],
        "turns": int(result["turns"]),
        "candidate_metrics": candidate_metrics,
        "opponent_metrics": opponent_metrics,
        "candidate_tieq": _tieq(
            candidate_metrics,
            won_early=candidate_won and int(result["turns"]) < ROUND_LIMIT,
        ),
        "opponent_tieq": _tieq(
            opponent_metrics,
            won_early=opponent_won and int(result["turns"]) < ROUND_LIMIT,
        ),
        "analysis_path": str(analysis_output.relative_to(ROOT)) if analysis_output.is_relative_to(ROOT) else str(analysis_output),
        "match_id": job.get("match_id"),
        "display_label": job.get("display_label"),
    }


def _progress_interval(total_games: int) -> int:
    if total_games <= MAX_PROGRESS_UPDATES:
        return 1
    return max(1, total_games // MAX_PROGRESS_UPDATES)


def build_schedule(
    candidate: str,
    candidate_path: Path,
    opponent: str,
    opponent_path: Path,
    maps: list[Path],
    games_per_opponent: int,
    *,
    one_order: bool,
    schedule_seed: int,
    output_dir: Path,
    tle_ms: int | None = None,
) -> list[dict[str, Any]]:
    rng = random.Random(f"{schedule_seed}:{candidate}:{opponent}")
    jobs: list[dict[str, Any]] = []
    if one_order:
        seat_tags = ["AB"] * games_per_opponent
    elif games_per_opponent % 2 == 0:
        seat_tags = ["AB"] * (games_per_opponent // 2) + ["BA"] * (games_per_opponent // 2)
        rng.shuffle(seat_tags)
    else:
        seat_tags = ["AB" if rng.random() < 0.5 else "BA" for _ in range(games_per_opponent)]
    for index in range(games_per_opponent):
        seat_tag = seat_tags[index]
        if seat_tag == "AB":
            bot_a = candidate
            bot_b = opponent
            bot_a_path = candidate_path
            bot_b_path = opponent_path
        else:
            bot_a = opponent
            bot_b = candidate
            bot_a_path = opponent_path
            bot_b_path = candidate_path

        map_path = rng.choice(maps)
        game_seed = rng.randrange(1, 2_147_483_647)
        replay_path = (
            output_dir
            / "replays"
            / f"{_safe_token(candidate)}_vs_{_safe_token(opponent)}_g{index + 1:02d}_{seat_tag}_{_safe_token(map_path.stem)}_seed_{game_seed}.replay26"
        )
        jobs.append(
            {
                "candidate": candidate,
                "opponent": opponent,
                "bot_a": bot_a,
                "bot_b": bot_b,
                "bot_a_path": str(bot_a_path),
                "bot_b_path": str(bot_b_path),
                "map_path": str(map_path),
                "seed": game_seed,
                "replay_path": str(replay_path),
                "analysis_output": str(output_dir / "replay_analysis" / f"{replay_path.stem}.json"),
                "match_id": f"g{index + 1:02d}_{seat_tag}_{_safe_token(map_path.stem)}_{game_seed}",
                "display_label": f"{opponent}:{map_path.stem}:{seat_tag}",
                "tle_ms": tle_ms,
            }
        )
    return jobs


def build_tournament_schedule(
    candidate: str,
    candidate_path: Path,
    opponents: list[tuple[str, Path]],
    maps: list[Path],
    seeds: list[int],
    *,
    output_dir: Path,
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for opponent, opponent_path in opponents:
        opp_safe = _safe_token(opponent)
        for map_path in maps:
            map_safe = _safe_token(map_path.stem)
            for seed in seeds:
                for candidate_is_team_a in (True, False):
                    if candidate_is_team_a:
                        bot_a = candidate
                        bot_b = opponent
                        bot_a_path = candidate_path
                        bot_b_path = opponent_path
                        seat_tag = "A"
                        replay_seat = "AB"
                    else:
                        bot_a = opponent
                        bot_b = candidate
                        bot_a_path = opponent_path
                        bot_b_path = candidate_path
                        seat_tag = "B"
                        replay_seat = "BA"

                    match_id = f"{opp_safe}_{map_safe}_s{seed}_{seat_tag}"
                    replay_path = (
                        output_dir
                        / "replays"
                        / f"{_safe_token(candidate)}_vs_{opp_safe}_{map_safe}_seed_{seed}_{replay_seat}.replay26"
                    )
                    display_label = f"{opp_safe}:{map_safe}:{seat_tag}:s{seed}"
                    jobs.append(
                        {
                            "candidate": candidate,
                            "opponent": opponent,
                            "bot_a": bot_a,
                            "bot_b": bot_b,
                            "bot_a_path": str(bot_a_path),
                            "bot_b_path": str(bot_b_path),
                            "map_path": str(map_path),
                            "seed": int(seed),
                            "replay_path": str(replay_path),
                            "analysis_output": str(output_dir / "replay_analysis" / f"{replay_path.stem}.json"),
                            "match_id": match_id,
                            "display_label": display_label,
                        }
                    )
    return jobs


def _run_job_safe(job: dict[str, Any]) -> dict[str, Any]:
    try:
        return {
            "ok": True,
            "job": job,
            "record": _run_matrix_job(job),
        }
    except Exception as exc:  # pragma: no cover - best effort shell backend mode
        return {
            "ok": False,
            "job": job,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def run_jobs(
    pending_jobs: list[dict[str, Any]],
    *,
    jobs: int = 1,
    progress: bool = True,
    on_start: Callable[[dict[str, Any]], None] | None = None,
    on_finish: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    total_games = len(pending_jobs)
    if total_games == 0:
        return [], []

    progress_every = _progress_interval(total_games)

    def _report_progress(completed: int) -> None:
        if progress and (completed == total_games or completed % progress_every == 0):
            print(f"Completed {completed}/{total_games} games", flush=True)

    if jobs <= 1:
        records: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for index, job in enumerate(pending_jobs, start=1):
            if on_start is not None:
                on_start(job)
            outcome = _run_job_safe(job)
            if on_finish is not None:
                on_finish(job, outcome)
            if outcome["ok"]:
                records.append(outcome["record"])
            else:
                failures.append(outcome)
            _report_progress(index)
        return records, failures

    outcomes_by_index: dict[int, dict[str, Any]] = {}
    pending_iter = iter(enumerate(pending_jobs))

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        inflight: dict[Any, tuple[int, dict[str, Any]]] = {}
        initial_slots = min(jobs, total_games)
        for _ in range(initial_slots):
            idx, job = next(pending_iter)
            if on_start is not None:
                on_start(job)
            inflight[pool.submit(_run_job_safe, job)] = (idx, job)

        completed = 0
        while inflight:
            done_futures, _ = wait(tuple(inflight.keys()), return_when=FIRST_COMPLETED)
            for finished in done_futures:
                idx, job = inflight.pop(finished)
                outcome = finished.result()
                outcomes_by_index[idx] = outcome
                completed += 1
                if on_finish is not None:
                    on_finish(job, outcome)
                _report_progress(completed)

                try:
                    next_idx, next_job = next(pending_iter)
                except StopIteration:
                    continue
                if on_start is not None:
                    on_start(next_job)
                inflight[pool.submit(_run_job_safe, next_job)] = (next_idx, next_job)

    ordered = [outcomes_by_index[index] for index in range(total_games)]
    records = [outcome["record"] for outcome in ordered if outcome["ok"]]
    failures = [outcome for outcome in ordered if not outcome["ok"]]
    return records, failures


def run_matrix(
    candidate: str,
    candidate_path: Path,
    opponents: list[tuple[str, Path]],
    maps: list[Path],
    games_per_opponent: int,
    *,
    one_order: bool,
    schedule_seed: int,
    output_dir: Path,
    jobs: int = 1,
    tle_ms: int | None = None,
) -> list[dict[str, Any]]:
    pending_jobs: list[dict[str, Any]] = []
    for opponent, opponent_path in opponents:
        pending_jobs.extend(
            build_schedule(
                candidate,
                candidate_path,
                opponent,
                opponent_path,
                maps,
                games_per_opponent,
                one_order=one_order,
                schedule_seed=schedule_seed,
                output_dir=output_dir,
                tle_ms=tle_ms,
            )
        )
    records, failures = run_jobs(pending_jobs, jobs=jobs, progress=True)
    if failures:
        print(f"Warning: {len(failures)} games failed", file=sys.stderr)
    return records


def summarize_matrix(candidate: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    per_opponent: dict[str, dict[str, Any]] = {}

    for record in records:
        stats = per_opponent.setdefault(record["opponent"], _new_bucket())
        stats["games"] += 1
        stats["turns_sum"] += int(record["turns"])
        stats["candidate_tieq_sum"] += int(record["candidate_tieq"])
        stats["candidate_tieq_worst"] = (
            int(record["candidate_tieq"])
            if stats["candidate_tieq_worst"] is None
            else min(int(stats["candidate_tieq_worst"]), int(record["candidate_tieq"]))
        )

        metrics = record["candidate_metrics"]
        stats["candidate_delivered_titanium"] += int(metrics["delivered_titanium"])
        stats["candidate_delivered_refined_axionite"] += int(metrics["delivered_refined_axionite"])
        stats["candidate_mined_titanium"] += int(metrics["mined_titanium"])
        stats["candidate_mined_axionite"] += int(metrics["mined_axionite"])
        stats["candidate_harvesters_alive"] += int(metrics["harvesters_alive"])
        stats["candidate_stored_titanium"] += int(metrics["stored_titanium"])
        stats["candidate_stored_axionite"] += int(metrics["stored_axionite"])
        stats["candidate_builder_turns"] += int(metrics.get("builder_turns", 0))
        for label in EXEC_PRESSURE_LABELS:
            stats[_candidate_builder_pressure_count_field(label)] += int(
                metrics.get(_builder_pressure_count_field(label), 0)
            )
        stats["candidate_tled_turns"] += int(metrics["tled_turns"])
        if int(metrics["builder_max_small_loop_streak"]) >= 1:
            stats["candidate_small_loop_games"] += 1
        win_condition = str(record.get("win_condition", "unknown"))
        stats["win_condition_counts"][win_condition] = (
            int(stats["win_condition_counts"].get(win_condition, 0)) + 1
        )

        if _candidate_won(record):
            stats["wins"] += 1
        elif record["winner"] in {"A", "B"}:
            stats["losses"] += 1
        else:
            stats["draws"] += 1

    total_games = len(records)
    total_wins = sum(stats["wins"] for stats in per_opponent.values())
    total_long_tled = sum(stats["candidate_tled_turns"] for stats in per_opponent.values())
    total_small_loop_games = sum(stats["candidate_small_loop_games"] for stats in per_opponent.values())
    total_builder_turns = sum(stats["candidate_builder_turns"] for stats in per_opponent.values())

    for stats in per_opponent.values():
        games = int(stats["games"])
        stats["win_rate"] = float(stats["wins"]) / float(games) if games else 0.0
        stats["average_turns"] = float(stats["turns_sum"]) / float(games) if games else 0.0
        stats["candidate_tieq_avg"] = float(stats["candidate_tieq_sum"]) / float(games) if games else 0.0
        stats["candidate_tieq_worst"] = int(stats["candidate_tieq_worst"] or 0)
        stats["candidate_avg_delivered_titanium"] = (
            float(stats["candidate_delivered_titanium"]) / float(games) if games else 0.0
        )
        stats["candidate_avg_delivered_refined_axionite"] = (
            float(stats["candidate_delivered_refined_axionite"]) / float(games) if games else 0.0
        )
        stats["candidate_avg_mined_titanium"] = (
            float(stats["candidate_mined_titanium"]) / float(games) if games else 0.0
        )
        stats["candidate_avg_mined_axionite"] = (
            float(stats["candidate_mined_axionite"]) / float(games) if games else 0.0
        )
        builder_turns = int(stats["candidate_builder_turns"])
        for label in EXEC_PRESSURE_LABELS:
            stats[_candidate_builder_pressure_rate_field(label)] = (
                float(stats[_candidate_builder_pressure_count_field(label)]) / float(builder_turns)
                if builder_turns
                else 0.0
            )
        stats["win_condition_counts"] = dict(sorted(stats["win_condition_counts"].items()))

    aggregate_tieq_avg = (
        sum(stats["candidate_tieq_sum"] for stats in per_opponent.values()) / float(total_games)
        if total_games
        else 0.0
    )
    aggregate_tieq_worst = min(
        (int(record["candidate_tieq"]) for record in records),
        default=0,
    )
    map_variance = pstdev([stats["win_rate"] for stats in per_opponent.values()]) if len(per_opponent) > 1 else 0.0

    summary = {
        "candidate": candidate,
        "games": total_games,
        "aggregate_win_rate": float(total_wins) / float(total_games) if total_games else 0.0,
        "aggregate_tieq_avg": aggregate_tieq_avg,
        "aggregate_tieq_worst": aggregate_tieq_worst,
        "candidate_builder_turns": total_builder_turns,
        "candidate_tled_turns": total_long_tled,
        "candidate_small_loop_games": total_small_loop_games,
        "map_variance": map_variance,
        "per_opponent": dict(sorted(per_opponent.items())),
    }
    for label in EXEC_PRESSURE_LABELS:
        count = sum(stats[_candidate_builder_pressure_count_field(label)] for stats in per_opponent.values())
        summary[_candidate_builder_pressure_count_field(label)] = count
        summary[_candidate_builder_pressure_rate_field(label)] = (
            float(count) / float(total_builder_turns) if total_builder_turns else 0.0
        )
    return summary


def evaluate_promotion_gate(
    candidate: str,
    summary: dict[str, Any],
    *,
    win_rate_threshold: float = PROMOTION_WIN_RATE_THRESHOLD,
    tieq_avg_threshold: float = PROMOTION_TIEQ_AVG_THRESHOLD,
    tieq_worst_threshold: int = PROMOTION_TIEQ_WORST_THRESHOLD,
) -> dict[str, Any]:
    failing_opponents: list[str] = []
    failing_details: dict[str, list[str]] = {}

    for name, stats in summary.get("per_opponent", {}).items():
        failures: list[str] = []
        if stats.get("win_rate", 0.0) < win_rate_threshold:
            failures.append("win_rate")
        if stats.get("candidate_tieq_avg", 0.0) < tieq_avg_threshold:
            failures.append("tieq_avg")
        if tieq_worst_threshold > 0 and stats.get("candidate_tieq_worst", 0) < tieq_worst_threshold:
            failures.append("tieq_worst")
        if failures:
            failing_opponents.append(name)
            failing_details[name] = failures

    return {
        "candidate": candidate,
        "win_rate_threshold": win_rate_threshold,
        "tieq_avg_threshold": tieq_avg_threshold,
        "tieq_worst_threshold": tieq_worst_threshold,
        "qualifies_for_promotion": len(failing_opponents) == 0 and bool(summary.get("per_opponent")),
        "failing_opponents": failing_opponents,
        "failing_details": failing_details,
    }


def default_opponents(candidate: str, max_opponents: int) -> list[tuple[str, Path]]:
    names = [name for name in available_bot_names() if name not in {candidate, "none"}]
    if not names:
        raise SystemExit("No default opponents available in bots/")
    return [(name, resolve_bot_path(name)) for name in names[:max_opponents]]


def resolve_opponents(
    candidate: str,
    specs: list[str] | None,
    *,
    max_opponents: int,
) -> list[tuple[str, Path]]:
    if not specs:
        return default_opponents(candidate, max_opponents)

    opponents: list[tuple[str, Path]] = []
    for spec in _dedupe_ordered(specs):
        path = resolve_bot_path(spec)
        name = bot_label(path)
        if name == candidate:
            raise SystemExit("Studied opponent set cannot include the candidate itself")
        opponents.append((name, path))
    return opponents


def resolve_tournament_maps(maps_dir: str | Path) -> list[Path]:
    maps_root = Path(maps_dir)
    if not maps_root.is_absolute():
        maps_root = (ROOT / maps_root).resolve()
    if not maps_root.is_dir():
        raise SystemExit(f"Maps directory not found: {maps_root}")

    maps = sorted(maps_root.glob("*.map26"))
    if not maps:
        raise SystemExit(f"No .map26 files found in {maps_root}")
    return maps


def _winner_name_from_record(record: dict[str, Any]) -> str:
    if record["winner"] == "A":
        return str(record["bot_a"])
    if record["winner"] == "B":
        return str(record["bot_b"])
    return "Draw"


def _emit_machine_line(*parts: object) -> None:
    cleaned = [str(part).replace("\t", " ").replace("\n", " ") for part in parts]
    print("\t".join(cleaned), flush=True)


def _print_summary(summary: dict[str, Any], output_path: Path) -> None:
    print(
        f"{summary['candidate']}: "
        f"{summary['aggregate_win_rate']:.1%} win rate over {summary['games']} games, "
        f"avg TiEq {summary['aggregate_tieq_avg']:.1f}, "
        f"worst TiEq {summary['aggregate_tieq_worst']}, "
        f"TLE turns {summary['candidate_tled_turns']}, "
        f"builder >0.5/1/1.5/2ms {_format_builder_pressure_rates(summary)}"
    )
    for opponent, stats in summary.get("per_opponent", {}).items():
        print(
            f"  {opponent}: {stats['wins']}-{stats['losses']}"
            f" ({stats['draws']} draws), "
            f"win rate {stats['win_rate']:.1%}, "
            f"avg TiEq {stats['candidate_tieq_avg']:.1f}, "
            f"TLE turns {stats['candidate_tled_turns']}, "
            f"builder >0.5/1/1.5/2ms {_format_builder_pressure_rates(stats)}, "
            f"wins {stats['win_condition_counts']}"
        )
    print(f"Report: {output_path}")


def run_tournament_backend(args: argparse.Namespace) -> None:
    if not args.opponents and not args.opponents_compat:
        raise SystemExit("tournament backend requires at least one opponent")

    candidate_path = resolve_bot_path(args.candidate)
    candidate = bot_label(candidate_path)
    opponent_specs = args.opponents if args.opponents else args.opponents_compat
    opponents = resolve_opponents(candidate, opponent_specs, max_opponents=args.max_opponents)
    maps = resolve_tournament_maps(args.tournament_maps_dir)
    seeds = args.tournament_seeds or [DEFAULT_SCHEDULE_SEED]
    if any(seed < 0 for seed in seeds):
        raise SystemExit("--tournament-seeds cannot contain negative values")

    jobs = resolve_jobs(args.jobs)
    output_dir = ROOT / ".dist"
    pending_jobs = build_tournament_schedule(
        candidate,
        candidate_path,
        opponents,
        maps,
        seeds,
        output_dir=output_dir,
    )

    output_path = Path(args.output) if args.output else default_tournament_output_path(candidate, [name for name, _ in opponents])
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    _emit_machine_line("META", candidate, str(output_path), len(pending_jobs), jobs)
    for job in pending_jobs:
        _emit_machine_line("QUEUE", job["match_id"], job["display_label"])
    _emit_machine_line("BEGIN")

    def on_start(job: dict[str, Any]) -> None:
        _emit_machine_line("START", job["match_id"])

    def on_finish(job: dict[str, Any], outcome: dict[str, Any]) -> None:
        if outcome["ok"]:
            record = outcome["record"]
            _emit_machine_line(
                "DONE",
                job["match_id"],
                _winner_name_from_record(record),
                record["turns"],
                record["replay_path"],
                record["analysis_path"],
            )
            return
        _emit_machine_line("FAIL", job["match_id"], outcome["error"])

    records, failures = run_jobs(
        pending_jobs,
        jobs=jobs,
        progress=False,
        on_start=on_start,
        on_finish=on_finish,
    )

    summary = summarize_matrix(candidate, records)
    gate = evaluate_promotion_gate(
        candidate,
        summary,
        win_rate_threshold=args.win_rate_threshold,
        tieq_avg_threshold=args.tieq_avg_threshold,
        tieq_worst_threshold=args.tieq_worst_threshold,
    )
    payload = {
        "mode": "tournament",
        "candidate": candidate,
        "opponents": [name for name, _ in opponents],
        "maps": [path.name for path in maps],
        "maps_dir": str(Path(args.tournament_maps_dir)),
        "seeds": seeds,
        "jobs": jobs,
        "games_requested": len(pending_jobs),
        "games_completed": len(records),
        "games_failed": len(failures),
        "records": records,
        "failures": [
            {
                "match_id": outcome["job"].get("match_id"),
                "display_label": outcome["job"].get("display_label"),
                "opponent": outcome["job"].get("opponent"),
                "map_name": Path(outcome["job"]["map_path"]).name,
                "seed": int(outcome["job"]["seed"]),
                "error": outcome["error"],
                "traceback": outcome["traceback"],
            }
            for outcome in failures
        ],
        "summary": summary,
        "promotion_gate": gate,
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _emit_machine_line("REPORT", str(output_path))
    _emit_machine_line("END")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", help="Candidate bot name or path.")
    parser.add_argument("opponents", nargs="*", help="Optional opponent bot names or paths.")
    parser.add_argument("--maps", nargs="*", default=None, help="Optional map filenames from maps/.")
    parser.add_argument("--games-per-opponent", type=int, default=DEFAULT_GAMES_PER_OPPONENT)
    parser.add_argument(
        "--jobs",
        type=int,
        default=None,
        help=f"Parallel worker processes for game execution (1-{MAX_WORKERS}, default auto-capped).",
    )
    parser.add_argument("--output", default=None, help="Optional JSON output path.")
    parser.add_argument(
        "--tle-ms",
        type=int,
        default=None,
        help="Optional local `cambc run --tle` cap in milliseconds per round.",
    )
    parser.add_argument(
        "--opponents",
        dest="opponents_compat",
        nargs="*",
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--schedule-seed", type=int, default=DEFAULT_SCHEDULE_SEED, help=argparse.SUPPRESS)
    parser.add_argument("--max-opponents", type=int, default=DEFAULT_MAX_OPPONENTS, help=argparse.SUPPRESS)
    parser.add_argument("--win-rate-threshold", type=float, default=PROMOTION_WIN_RATE_THRESHOLD, help=argparse.SUPPRESS)
    parser.add_argument("--tieq-avg-threshold", type=float, default=PROMOTION_TIEQ_AVG_THRESHOLD, help=argparse.SUPPRESS)
    parser.add_argument("--tieq-worst-threshold", type=int, default=PROMOTION_TIEQ_WORST_THRESHOLD, help=argparse.SUPPRESS)
    parser.add_argument("--one-order", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--tournament-backend", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--tournament-maps-dir", default="maps", help=argparse.SUPPRESS)
    parser.add_argument("--tournament-seeds", nargs="*", type=int, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.tournament_backend:
        run_tournament_backend(args)
        return

    if args.games_per_opponent < 1:
        raise SystemExit("--games-per-opponent must be at least 1")
    if args.tle_ms is not None and args.tle_ms < 0:
        raise SystemExit("--tle-ms must be non-negative")

    candidate_path = resolve_bot_path(args.candidate)
    candidate = bot_label(candidate_path)
    selected_maps = default_maps() if args.maps is None else [resolve_map_path(name) for name in args.maps]
    opponent_specs = args.opponents if args.opponents else args.opponents_compat
    opponents = resolve_opponents(
        candidate,
        opponent_specs,
        max_opponents=args.max_opponents,
    )
    jobs = resolve_jobs(args.jobs)
    records = run_matrix(
        candidate,
        candidate_path,
        opponents,
        selected_maps,
        args.games_per_opponent,
        one_order=args.one_order,
        schedule_seed=args.schedule_seed,
        output_dir=ROOT / ".dist",
        jobs=jobs,
        tle_ms=args.tle_ms,
    )
    summary = summarize_matrix(candidate, records)
    gate = evaluate_promotion_gate(
        candidate,
        summary,
        win_rate_threshold=args.win_rate_threshold,
        tieq_avg_threshold=args.tieq_avg_threshold,
        tieq_worst_threshold=args.tieq_worst_threshold,
    )

    payload = {
        "candidate": candidate,
        "opponents": [name for name, _ in opponents],
        "maps": [path.name for path in selected_maps],
        "games_per_opponent": args.games_per_opponent,
        "schedule_seed": args.schedule_seed,
        "jobs": jobs,
        "tle_ms": args.tle_ms,
        "max_opponents": args.max_opponents,
        "records": records,
        "summary": summary,
        "promotion_gate": gate,
    }
    output_path = (
        Path(args.output)
        if args.output
        else default_output_path(candidate, [name for name, _ in opponents])
    )
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _print_summary(summary, output_path)


if __name__ == "__main__":
    main()
