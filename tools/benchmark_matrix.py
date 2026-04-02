"""Run a candidate bot against a studied opponent set with per-opponent TiEq gating."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import random
import sys
from pathlib import Path
from statistics import pstdev
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.analyze_replay import analyze_replay_path
from tools.benchmark import (
    available_bot_names,
    bot_label,
    default_maps,
    resolve_map_path,
    resolve_bot_path,
    run_local_game,
)


DEFAULT_GAMES_PER_OPPONENT = 32
MAX_WORKERS = 8
DEFAULT_MAX_OPPONENTS = 5
PROMOTION_WIN_RATE_THRESHOLD = 0.8
PROMOTION_TIEQ_AVG_THRESHOLD = 100000.0
PROMOTION_TIEQ_WORST_THRESHOLD = 50000
MAX_REMEDIATION_ROUNDS = 2
DEFAULT_SCHEDULE_SEED = 1
EARLY_WIN_TIEQ_BONUS = 100000
ROUND_LIMIT = 2000


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


def _new_bucket() -> dict[str, Any]:
    return {
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
        "candidate_tled_turns": 0,
        "candidate_small_loop_games": 0,
    }


def _candidate_won(record: dict[str, Any]) -> bool:
    return (
        (record["candidate_team"] == "TEAM_A" and record["winner"] == "A")
        or (record["candidate_team"] == "TEAM_B" and record["winner"] == "B")
    )


def _extract_metrics(analysis: dict[str, Any]) -> dict[str, int]:
    delivered = analysis.get("delivered_resources", {})
    final_resources = analysis.get("final_resources", {})
    alive_by_kind = analysis.get("alive_by_kind", {})
    return {
        "delivered_titanium": int(delivered.get("titanium", 0)),
        "delivered_refined_axionite": int(delivered.get("refined_axionite", 0)),
        "mined_titanium": int(final_resources.get("titanium_collected", 0)),
        "mined_axionite": int(final_resources.get("axionite_collected", 0)),
        "stored_titanium": int(final_resources.get("titanium", 0)),
        "stored_axionite": int(final_resources.get("axionite", 0)),
        "harvesters_alive": int(alive_by_kind.get("harvester", 0)),
        "tled_turns": int(analysis.get("tled_turns", 0)),
        "builder_max_small_loop_streak": int(analysis.get("builder_max_small_loop_streak", 0)),
    }


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
    result = run_local_game(bot_a_path, bot_b_path, map_path, replay_path, int(job["seed"]))

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
        "replay_path": str(replay_path.relative_to(ROOT)),
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
        "analysis_path": str(analysis_output.relative_to(ROOT)),
    }


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
) -> list[dict[str, Any]]:
    rng = random.Random(f"{schedule_seed}:{candidate}:{opponent}")
    jobs: list[dict[str, Any]] = []
    for index in range(games_per_opponent):
        if one_order:
            bot_a = candidate
            bot_b = opponent
            bot_a_path = candidate_path
            bot_b_path = opponent_path
            seat_tag = "AB"
        else:
            if rng.random() < 0.5:
                bot_a = candidate
                bot_b = opponent
                bot_a_path = candidate_path
                bot_b_path = opponent_path
                seat_tag = "AB"
            else:
                bot_a = opponent
                bot_b = candidate
                bot_a_path = opponent_path
                bot_b_path = candidate_path
                seat_tag = "BA"

        map_path = rng.choice(maps)
        game_seed = rng.randrange(1, 2_147_483_647)
        replay_path = (
            output_dir
            / "replays"
            / f"{candidate}_vs_{opponent}_g{index + 1:02d}_{seat_tag}_{map_path.stem}_seed_{game_seed}.replay26"
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
            }
        )
    return jobs


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
            )
        )
    if jobs <= 1:
        return [_run_matrix_job(job) for job in pending_jobs]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(_run_matrix_job, pending_jobs))


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
        stats["candidate_tled_turns"] += int(metrics["tled_turns"])
        if int(metrics["builder_max_small_loop_streak"]) >= 1:
            stats["candidate_small_loop_games"] += 1

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

    return {
        "candidate": candidate,
        "games": total_games,
        "aggregate_win_rate": float(total_wins) / float(total_games) if total_games else 0.0,
        "aggregate_tieq_avg": aggregate_tieq_avg,
        "aggregate_tieq_worst": aggregate_tieq_worst,
        "candidate_tled_turns": total_long_tled,
        "candidate_small_loop_games": total_small_loop_games,
        "map_variance": map_variance,
        "per_opponent": dict(sorted(per_opponent.items())),
    }


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
        if stats.get("candidate_tieq_worst", 0) < tieq_worst_threshold:
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


def remediation_recommendation(gate: dict[str, Any], remediation_round: int) -> str:
    if gate["qualifies_for_promotion"]:
        return "promote"
    if remediation_round < 1:
        return "remediate_round_1"
    if remediation_round < MAX_REMEDIATION_ROUNDS:
        return "remediate_round_2"
    return "deactivate_from_active_flow"


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
    allow_single_opponent: bool,
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

    if len(opponents) < 2 and not allow_single_opponent:
        raise SystemExit("Use --allow-single-opponent if you want a one-opponent studied set")
    return opponents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", help="Candidate bot name or path.")
    parser.add_argument("--opponents", nargs="*", default=None, help="Opponent bot names or paths.")
    parser.add_argument("--maps", nargs="*", default=None, help="Optional map filenames from maps/.")
    parser.add_argument("--games-per-opponent", type=int, default=DEFAULT_GAMES_PER_OPPONENT)
    parser.add_argument("--schedule-seed", type=int, default=DEFAULT_SCHEDULE_SEED)
    parser.add_argument(
        "--jobs",
        type=int,
        default=None,
        help=f"Parallel worker processes for game execution (1-{MAX_WORKERS}, default auto-capped).",
    )
    parser.add_argument(
        "--max-opponents",
        type=int,
        default=DEFAULT_MAX_OPPONENTS,
        help=f"Default-opponent cap when --opponents is omitted. Default: {DEFAULT_MAX_OPPONENTS}.",
    )
    parser.add_argument(
        "--allow-single-opponent",
        action="store_true",
        help="Allow explicit one-opponent studied sets for quick profiling runs.",
    )
    parser.add_argument(
        "--remediation-round",
        type=int,
        choices=[0, 1, 2],
        default=0,
        help="Staged rejection round (0 initial run, then 1 or 2 for remediation attempts).",
    )
    parser.add_argument("--win-rate-threshold", type=float, default=PROMOTION_WIN_RATE_THRESHOLD)
    parser.add_argument("--tieq-avg-threshold", type=float, default=PROMOTION_TIEQ_AVG_THRESHOLD)
    parser.add_argument("--tieq-worst-threshold", type=int, default=PROMOTION_TIEQ_WORST_THRESHOLD)
    parser.add_argument("--one-order", action="store_true", help="Disable random seat assignment.")
    parser.add_argument("--output", default=".dist/reports/benchmark_matrix.json")
    args = parser.parse_args()

    if args.games_per_opponent < 1:
        raise SystemExit("--games-per-opponent must be at least 1")

    candidate_path = resolve_bot_path(args.candidate)
    candidate = bot_label(candidate_path)
    selected_maps = default_maps() if args.maps is None else [resolve_map_path(name) for name in args.maps]
    opponents = resolve_opponents(
        candidate,
        args.opponents,
        max_opponents=args.max_opponents,
        allow_single_opponent=args.allow_single_opponent,
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
    )
    summary = summarize_matrix(candidate, records)
    gate = evaluate_promotion_gate(
        candidate,
        summary,
        win_rate_threshold=args.win_rate_threshold,
        tieq_avg_threshold=args.tieq_avg_threshold,
        tieq_worst_threshold=args.tieq_worst_threshold,
    )
    recommendation = remediation_recommendation(gate, args.remediation_round)

    payload = {
        "candidate": candidate,
        "opponents": [name for name, _ in opponents],
        "maps": [path.name for path in selected_maps],
        "games_per_opponent": args.games_per_opponent,
        "schedule_seed": args.schedule_seed,
        "jobs": jobs,
        "max_opponents": args.max_opponents,
        "allow_single_opponent": args.allow_single_opponent,
        "remediation_round": args.remediation_round,
        "max_remediation_rounds": MAX_REMEDIATION_ROUNDS,
        "records": records,
        "summary": summary,
        "promotion_gate": gate,
        "recommendation": recommendation,
    }
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
