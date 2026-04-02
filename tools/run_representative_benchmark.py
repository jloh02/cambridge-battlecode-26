"""Run a seat-symmetric benchmark on a fixed representative map set."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import sys
from pathlib import Path


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
DEFAULT_OUTPUT_PATH = ROOT / ".dist" / "reports" / "representative_benchmark.json"
DEFAULT_REPLAY_BASE_DIR = ROOT / "replays" / "representative_benchmark"


def representative_maps() -> list[Path]:
    return [resolve_map_path(name) for name in REPRESENTATIVE_MAPS]


def default_run_replay_dir(base_dir: Path, *, now: datetime | None = None) -> Path:
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return base_dir / timestamp


def run_representative_benchmark(
    bot_a_spec: str,
    bot_b_spec: str,
    *,
    maps: list[str] | None = None,
    seeds: list[int] | None = None,
    replay_dir: Path | None = None,
    quiet: bool = True,
    swap_seats: bool = True,
) -> dict[str, object]:
    bot_a = resolve_bot_path(bot_a_spec)
    bot_b = resolve_bot_path(bot_b_spec)
    selected_maps = representative_maps() if maps is None else [resolve_map_path(spec) for spec in maps]
    selected_seeds = seeds or [1, 7]

    records: list[dict[str, object]] = []
    seat_pairs = [(bot_a, bot_b)]
    if swap_seats:
        seat_pairs.append((bot_b, bot_a))

    for left_bot, right_bot in seat_pairs:
        for map_path in selected_maps:
            for seed in selected_seeds:
                replay_path: Path | None = None
                if replay_dir is not None:
                    replay_path = replay_dir / (
                        f"{bot_label(left_bot)}_vs_{bot_label(right_bot)}_{map_path.stem}_seed_{seed}.replay26"
                    )
                result = run_local_game(
                    left_bot,
                    right_bot,
                    map_path,
                    replay_path or (ROOT / ".dist" / "tmp" / "discarded.replay26"),
                    seed,
                )
                record = {
                    "bot_a": bot_label(left_bot),
                    "bot_b": bot_label(right_bot),
                    "map_name": map_path.name,
                    "seed": seed,
                    "winner": result["winner"],
                    "winner_label": result["winner_label"],
                    "win_condition": result["win_condition"],
                    "turns": result["turns"],
                }
                if replay_path is not None:
                    record["replay_path"] = str(replay_path.relative_to(ROOT))
                records.append(record)
                if not quiet:
                    print(
                        f"{record['bot_a']} vs {record['bot_b']} on {record['map_name']} seed {seed}: "
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
    parser.add_argument("--seeds", nargs="*", type=int, default=[1, 7], help="Explicit game seeds.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="JSON output path.")
    parser.add_argument(
        "--replay-dir",
        default=str(DEFAULT_REPLAY_BASE_DIR),
        help="Replay output directory. The default appends a timestamped subdirectory.",
    )
    parser.add_argument("--no-swap-seats", action="store_true", help="Run only the bot_a vs bot_b seat order.")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-game progress lines.")
    args = parser.parse_args()

    replay_dir = Path(args.replay_dir) if args.replay_dir else None
    if replay_dir == DEFAULT_REPLAY_BASE_DIR:
        replay_dir = default_run_replay_dir(replay_dir)

    payload = run_representative_benchmark(
        args.bot_a,
        args.bot_b,
        maps=args.maps,
        seeds=args.seeds,
        replay_dir=replay_dir,
        quiet=args.quiet,
        swap_seats=not args.no_swap_seats,
    )
    if replay_dir is not None:
        replay_dir.mkdir(parents=True, exist_ok=True)
        payload["replay_dir"] = str(replay_dir.resolve())

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
