# Tools

This directory holds the repo's local benchmarking and replay-analysis scripts.

The public CLI is intentionally small. If you do not see an option documented
here, treat it as internal or research-only.

## Common Commands

```bash
python tools/benchmark.py jon-5 jon-4 --games 2
python tools/benchmark_matrix.py jon-5o jon-5 --games-per-opponent 4
python tools/analyze_replay.py file replay.replay26
python tools/analyze_replay.py match <match_id>
python tools/analyze_replay.py latest
python tools/report.py .dist/reports/jon-5_vs_jon-4.json
python tools/build_bots.py jon-5
```

## `benchmark.py`

Purpose: run a small local head-to-head set between two bots.

Simplest use:

```bash
python tools/benchmark.py jon-5 jon-4 --games 2
```

What it writes:

- replay files under `.dist/replays/`
- a JSON report under `.dist/reports/` unless `--output` is provided

What it prints:

- a compact win/loss summary
- the report path

## `benchmark_matrix.py`

Purpose: run one candidate against one or more opponents and summarize
per-opponent TiEq and win rate.

Simplest use:

```bash
python tools/benchmark_matrix.py jon-5o jon-5 --games-per-opponent 4
```

What it writes:

- replay files under `.dist/replays/`
- replay analyses under `.dist/replay_analysis/`
- a JSON matrix report under `.dist/reports/` unless `--output` is provided

What it prints:

- an aggregate candidate summary
- one short line per opponent
- the report path

If no opponents are supplied, the script falls back to the repo's default
opponent field.

## `analyze_replay.py`

Purpose: decode `.replay26` files and summarize timing, stalls, placements, and
resource outcomes.

Simplest use:

```bash
python tools/analyze_replay.py file replay.replay26
python tools/analyze_replay.py match <match_id>
python tools/analyze_replay.py latest
```

What it writes:

- JSON analysis files under `.dist/replay_analysis/` unless `--output` is
  provided
- downloaded remote replay files under `.dist/replay_analysis/replays/` when
  analyzing a remote match

What it prints:

- games analyzed
- winner / turn count when available
- per-team TLE, over-2ms, and max execution stats
- the report path

## `report.py`

Purpose: turn a benchmark JSON report into Markdown, and optionally CSV.

Simplest use:

```bash
python tools/report.py .dist/reports/jon-5_vs_jon-4.json
```

What it writes:

- nothing by default; Markdown goes to stdout
- optional Markdown/CSV files if flags are provided

## `build_bots.py`

Purpose: copy runnable bots into `.dist/bots/` for clean packaging or
submission prep.

Simplest use:

```bash
python tools/build_bots.py jon-5
```

What it writes:

- clean bot bundles under `.dist/bots/`

## `promotion_gate.py`

Internal helper module for staged promotion decisions.

It is not meant to be run directly as a normal user-facing command.
