"""Materialize optional clean bot bundles under `.dist/bots/`."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BOTS_DIR = ROOT / "bots"
DIST_BOTS = ROOT / ".dist" / "bots"


def available_bot_names() -> list[str]:
    return sorted(
        path.name
        for path in BOTS_DIR.iterdir()
        if path.is_dir() and (path / "main.py").is_file()
    )


def resolve_bot_dir(spec: str) -> Path:
    raw = Path(spec)
    candidates = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(Path.cwd() / raw)
        candidates.append(ROOT / raw)
        candidates.append(BOTS_DIR / spec)

    for candidate in candidates:
        if candidate.is_dir() and (candidate / "main.py").is_file():
            return candidate.resolve()

    raise SystemExit(f"Could not resolve bot directory from {spec!r}")


def _copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination, ignore_errors=True)
    if destination.exists():
        raise RuntimeError(f"Could not clean bundle destination: {destination}")
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def build_bot_bundle(spec: str) -> Path:
    source_dir = resolve_bot_dir(spec)
    bundle_root = DIST_BOTS / source_dir.name

    DIST_BOTS.mkdir(parents=True, exist_ok=True)
    _copy_tree(source_dir, bundle_root)
    cambattle_dir = ROOT / "cambattle"
    if cambattle_dir.is_dir():
        _copy_tree(cambattle_dir, bundle_root / "cambattle")
    return bundle_root


def build_all_bots() -> list[Path]:
    DIST_BOTS.mkdir(parents=True, exist_ok=True)
    return [build_bot_bundle(name) for name in available_bot_names()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "bots",
        nargs="*",
        help="Optional subset of bot names or bot directories. Default: build every runnable bot in bots/.",
    )
    args = parser.parse_args()

    built = [build_bot_bundle(spec) for spec in args.bots] if args.bots else build_all_bots()
    for path in built:
        print(path)


if __name__ == "__main__":
    main()
