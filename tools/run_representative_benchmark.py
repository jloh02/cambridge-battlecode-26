"""Run a seat-symmetric benchmark on a fixed representative map set."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.benchmark import (
    bot_label,
    resolve_bot_path,
    resolve_map_path,
    run_local_game,
    summarize_records,
)


REPRESENTATIVE_MAPS = [
    "default_small1.map26",
    "default_medium1.map26",
    "default_large1.map26",
    "corridors.map26",
    "wasteland.map26",
]
MAX_WORKERS = 8
REP_BENCH_DIR = ROOT / ".rep_bench"
DEFAULT_OUTPUT_PATH = REP_BENCH_DIR / "representative_benchmark.json"
DEFAULT_REPLAY_BASE_DIR = REP_BENCH_DIR / "replays"
DEFAULT_TMP_REPLAY_DIR = REP_BENCH_DIR / "tmp"


def representative_maps() -> list[Path]:
    return [resolve_map_path(name) for name in REPRESENTATIVE_MAPS]


def default_output_path(
    base_dir: Path,
    *,
    bot_a: str,
    bot_b: str,
    now: datetime | None = None,
) -> Path:
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return base_dir / f"{timestamp}_{bot_a}_vs_{bot_b}.json"


def default_run_replay_dir(
    base_dir: Path,
    *,
    bot_a: str,
    bot_b: str,
    now: datetime | None = None,
) -> Path:
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return base_dir / f"{timestamp}_{bot_a}_vs_{bot_b}"


def resolve_jobs(requested_jobs: int | None) -> int:
    if requested_jobs is None:
        return max(1, min(MAX_WORKERS, os.cpu_count() or 1))
    if requested_jobs < 1 or requested_jobs > MAX_WORKERS:
        raise SystemExit(f"--jobs must be between 1 and {MAX_WORKERS}")
    return requested_jobs


def _build_representative_jobs(
    bot_a: Path,
    bot_b: Path,
    *,
    selected_maps: list[Path],
    selected_seeds: list[int],
    replay_dir: Path | None,
    swap_seats: bool,
    debug: bool,
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    seat_pairs = [(bot_a, bot_b)]
    if swap_seats:
        seat_pairs.append((bot_b, bot_a))

    for left_bot, right_bot in seat_pairs:
        for map_path in selected_maps:
            for seed in selected_seeds:
                job_index = len(jobs) + 1
                replay_path: Path | None = None
                if replay_dir is not None:
                    replay_path = replay_dir / (
                        f"{bot_label(left_bot)}_vs_{bot_label(right_bot)}_{map_path.stem}_seed_{seed}.replay26"
                    )
                else:
                    replay_path = (
                        DEFAULT_TMP_REPLAY_DIR
                        / (
                            f"{job_index:02d}_{bot_label(left_bot)}_vs_{bot_label(right_bot)}_"
                            f"{map_path.stem}_seed_{seed}.replay26"
                        )
                    )
                jobs.append(
                    {
                        "bot_a_path": left_bot,
                        "bot_b_path": right_bot,
                        "map_path": map_path,
                        "seed": seed,
                        "replay_path": replay_path,
                        "persist_replay": replay_dir is not None,
                        "debug": debug,
                    }
                )
    return jobs


def _run_representative_job(job: dict[str, Any]) -> dict[str, object]:
    left_bot = Path(job["bot_a_path"])
    right_bot = Path(job["bot_b_path"])
    map_path = Path(job["map_path"])
    replay_path = Path(job["replay_path"])
    result = run_local_game(
        left_bot,
        right_bot,
        map_path,
        replay_path,
        int(job["seed"]),
        debug=bool(job["debug"]),
    )
    record: dict[str, object] = {
        "bot_a": bot_label(left_bot),
        "bot_b": bot_label(right_bot),
        "map_name": map_path.name,
        "seed": int(job["seed"]),
        "winner": result["winner"],
        "winner_label": result["winner_label"],
        "win_condition": result["win_condition"],
        "turns": result["turns"],
    }
    if bool(job["persist_replay"]):
        record["replay_path"] = str(replay_path.relative_to(ROOT))
    return record


def run_representative_benchmark(
    bot_a_spec: str,
    bot_b_spec: str,
    *,
    maps: list[str] | None = None,
    seeds: list[int] | None = None,
    replay_dir: Path | None = None,
    quiet: bool = True,
    swap_seats: bool = True,
    jobs: int | None = None,
    debug: bool = True,
) -> dict[str, object]:
    bot_a = resolve_bot_path(bot_a_spec)
    bot_b = resolve_bot_path(bot_b_spec)
    selected_maps = representative_maps() if maps is None else [resolve_map_path(spec) for spec in maps]
    selected_seeds = seeds or [1]
    worker_count = resolve_jobs(jobs)

    pending_jobs = _build_representative_jobs(
        bot_a,
        bot_b,
        selected_maps=selected_maps,
        selected_seeds=selected_seeds,
        replay_dir=replay_dir,
        swap_seats=swap_seats,
        debug=debug,
    )
    if worker_count <= 1:
        records = [_run_representative_job(job) for job in pending_jobs]
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            records = list(pool.map(_run_representative_job, pending_jobs))

    if not quiet:
        for record in records:
            print(
                f"{record['bot_a']} vs {record['bot_b']} on {record['map_name']} seed {record['seed']}: "
                f"{record['winner_label']} ({record['win_condition']}, turn {record['turns']})"
            )

    return {
        "bot_a": bot_label(bot_a),
        "bot_b": bot_label(bot_b),
        "maps": [path.name for path in selected_maps],
        "seeds": selected_seeds,
        "swap_seats": swap_seats,
        "records": records,
        "summary": summarize_records(bot_a, bot_b, records),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bot_a", help="Bot name or path.")
    parser.add_argument("bot_b", help="Bot name or path.")
    parser.add_argument("--maps", nargs="*", default=None, help="Override the representative map set.")
    parser.add_argument("--seeds", nargs="*", type=int, default=[1], help="Explicit game seeds.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="JSON output path.")
    parser.add_argument(
        "--replay-dir",
        default=str(DEFAULT_REPLAY_BASE_DIR),
        help="Replay output directory. The default appends a timestamped subdirectory.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=None,
        help=f"Parallel match worker count. Defaults to auto-detected parallelism up to {MAX_WORKERS}.",
    )
    parser.add_argument("--no-swap-seats", action="store_true", help="Run only the bot_a vs bot_b seat order.")
    parser.add_argument("--no-debug", action="store_true", help="Disable DEBUG replay stdout and indicators.")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-game progress lines.")
    args = parser.parse_args()

    bot_a_label = bot_label(resolve_bot_path(args.bot_a))
    bot_b_label = bot_label(resolve_bot_path(args.bot_b))
    run_started_at = datetime.now()

    replay_dir = Path(args.replay_dir) if args.replay_dir else None
    if replay_dir == DEFAULT_REPLAY_BASE_DIR:
        replay_dir = default_run_replay_dir(
            replay_dir,
            bot_a=bot_a_label,
            bot_b=bot_b_label,
            now=run_started_at,
        )

    payload = run_representative_benchmark(
        args.bot_a,
        args.bot_b,
        maps=args.maps,
        seeds=args.seeds,
        replay_dir=replay_dir,
        quiet=args.quiet,
        swap_seats=not args.no_swap_seats,
        jobs=args.jobs,
        debug=not args.no_debug,
    )
    if replay_dir is not None:
        replay_dir.mkdir(parents=True, exist_ok=True)
        payload["replay_dir"] = str(replay_dir.resolve())

    output_path = Path(args.output)
    if output_path == DEFAULT_OUTPUT_PATH:
        output_path = default_output_path(
            REP_BENCH_DIR,
            bot_a=bot_a_label,
            bot_b=bot_b_label,
            now=run_started_at,
        )
    elif not output_path.is_absolute():
        output_path = ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
