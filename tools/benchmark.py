"""Run direct local benchmarks between two bot directories or names."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BOTS_DIR = ROOT / "bots"
DIST_BOTS = ROOT / ".dist" / "bots"
MAPS_DIR = ROOT / "maps"
DEFAULT_OUTPUT = ROOT / ".dist" / "reports" / "benchmark.json"
WINNER_RE = re.compile(
    r"Winner:\s+(?P<label>.+?)\s+\((?P<condition>.+), turn (?P<turn>\d+)\)"
)


def available_bot_names() -> list[str]:
    return sorted(
        path.name
        for path in BOTS_DIR.iterdir()
        if path.is_dir() and (path / "main.py").is_file()
    )


def bot_label(path: Path) -> str:
    return path.name if path.is_dir() else path.stem


def resolve_bot_path(spec: str) -> Path:
    raw = Path(spec)
    candidates = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(Path.cwd() / raw)
        candidates.append(ROOT / raw)
        candidates.append(BOTS_DIR / spec)
        candidates.append(DIST_BOTS / spec)

    for candidate in candidates:
        if candidate.is_dir() and (candidate / "main.py").is_file():
            return candidate.resolve()
        if candidate.is_file() and candidate.suffix in {".py", ".zip"}:
            return candidate.resolve()

    raise SystemExit(f"Could not resolve bot from {spec!r}")


def default_maps() -> list[Path]:
    return sorted(MAPS_DIR.glob("*.map26"))


def resolve_map_path(spec: str) -> Path:
    raw = Path(spec)
    candidates = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(Path.cwd() / raw)
        candidates.append(ROOT / raw)
        candidates.append(MAPS_DIR / spec)

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise SystemExit(f"Could not resolve map from {spec!r}")


def _cambc_candidates() -> list[Path]:
    candidates: list[Path] = []
    env = os.getenv("CAMBC_BIN")
    if env:
        candidates.append(Path(env))

    which = shutil.which("cambc")
    if which:
        candidates.append(Path(which))

    pyenv = shutil.which("pyenv")
    if pyenv:
        result = subprocess.run(
            [pyenv, "prefix", "cambc"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            prefix = result.stdout.strip()
            if prefix:
                candidates.append(Path(prefix) / "bin" / "cambc")

    candidates.append(Path.home() / ".pyenv" / "versions" / "cambc" / "bin" / "cambc")

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def resolve_cambc_binary() -> Path:
    for candidate in _cambc_candidates():
        if not candidate.exists():
            continue
        result = subprocess.run(
            [str(candidate), "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return candidate
    raise SystemExit(
        "Could not find a working `cambc` binary. Activate the `cambc` pyenv environment "
        "or set CAMBC_BIN to the full path."
    )


def _parse_run_output(stdout: str, bot_a: Path, bot_b: Path) -> dict[str, object]:
    match = WINNER_RE.search(stdout)
    if match is None:
        raise RuntimeError(f"Could not parse cambc output:\n{stdout}")

    winner_label = match.group("label").strip()
    if winner_label == bot_label(bot_a):
        winner = "A"
    elif winner_label == bot_label(bot_b):
        winner = "B"
    else:
        winner = winner_label

    return {
        "winner": winner,
        "winner_label": winner_label,
        "win_condition": match.group("condition").strip(),
        "turns": int(match.group("turn")),
    }


def run_local_game(
    bot_a: Path,
    bot_b: Path,
    map_path: Path,
    replay_path: Path,
    seed: int,
    debug: bool = False,
) -> dict[str, object]:
    cambc = resolve_cambc_binary()
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(cambc),
        "run",
        str(bot_a),
        str(bot_b),
        str(map_path),
        "--seed",
        str(seed),
        "--replay",
        str(replay_path),
    ]
    env = os.environ.copy()
    env["DEBUG"] = "true" if debug else "false"
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "cambc run failed\n"
            f"command: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    parsed = _parse_run_output(result.stdout, bot_a, bot_b)
    parsed["stdout"] = result.stdout
    parsed["stderr"] = result.stderr
    return parsed


def _empty_summary() -> dict[str, object]:
    return {
        "games": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "win_rate": 0.0,
        "average_turns": 0.0,
    }


def summarize_records(bot_a: Path, bot_b: Path, records: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    label_a = bot_label(bot_a)
    label_b = bot_label(bot_b)
    summary = {
        label_a: _empty_summary(),
        label_b: _empty_summary(),
    }
    turns_sum = 0

    for record in records:
        turns_sum += int(record["turns"])
        winner = record["winner"]
        summary[label_a]["games"] += 1
        summary[label_b]["games"] += 1
        if winner == "A":
            summary[label_a]["wins"] += 1
            summary[label_b]["losses"] += 1
        elif winner == "B":
            summary[label_b]["wins"] += 1
            summary[label_a]["losses"] += 1
        else:
            summary[label_a]["draws"] += 1
            summary[label_b]["draws"] += 1

    for stats in summary.values():
        games = int(stats["games"])
        stats["win_rate"] = float(stats["wins"]) / float(games) if games else 0.0
        stats["average_turns"] = float(turns_sum) / float(games) if games else 0.0

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bot_a", help="Bot name or path.")
    parser.add_argument("bot_b", help="Bot name or path.")
    parser.add_argument("--maps", nargs="*", default=None, help="Optional map filenames or paths.")
    parser.add_argument("--seeds", nargs="*", type=int, default=[1], help="Explicit game seeds.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="JSON output path.")
    parser.add_argument(
        "--map-random-count",
        type=int,
        default=0,
        help="Append this many random maps from maps/ to the explicit map list.",
    )
    args = parser.parse_args()

    bot_a = resolve_bot_path(args.bot_a)
    bot_b = resolve_bot_path(args.bot_b)

    selected_maps = (
        [resolve_map_path(spec) for spec in args.maps]
        if args.maps
        else [default_maps()[0]]
    )
    if args.map_random_count > 0:
        pool = default_maps()
        rng = random.Random(1)
        selected_maps.extend(rng.choice(pool) for _ in range(args.map_random_count))

    records: list[dict[str, object]] = []
    for map_path in selected_maps:
        for seed in args.seeds:
            replay_path = (
                ROOT
                / ".dist"
                / "replays"
                / f"{bot_label(bot_a)}_vs_{bot_label(bot_b)}_{map_path.stem}_seed_{seed}.replay26"
            )
            result = run_local_game(bot_a, bot_b, map_path, replay_path, seed)
            records.append(
                {
                    "bot_a": bot_label(bot_a),
                    "bot_b": bot_label(bot_b),
                    "map_name": map_path.name,
                    "seed": seed,
                    "winner": result["winner"],
                    "winner_label": result["winner_label"],
                    "win_condition": result["win_condition"],
                    "turns": result["turns"],
                    "replay_path": str(replay_path.relative_to(ROOT)),
                }
            )

    payload = {
        "bot_a": bot_label(bot_a),
        "bot_b": bot_label(bot_b),
        "maps": [path.name for path in selected_maps],
        "seeds": args.seeds,
        "records": records,
        "summary": summarize_records(bot_a, bot_b, records),
    }
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
