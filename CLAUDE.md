## Working Rules

- Activate `.venv` when working with Python if it is not already active.
- Use `uv` as the package manager.
- Install new packages with `uv pip install ...`.

- You do not need to ask permission to run source .venv/bin/activate.

## Other important files
- CODEX_EXPLAINER.md describes what this game is about, and points you to the docs.

## Benchmarking for `@BenyAlbatross`

- For `@BenyAlbatross`, use `tools/run_representative_benchmark.py` for bot validation.
- For minor changes, run a smoke benchmark on:
  `default_small1.map26`, `default_medium1.map26`, and `default_large1.map26` with seed `1` only.
- For larger changes, run the full representative benchmark with seed `1` only.
- Use the default naming behavior for benchmark outputs and replay directories.
  Do not pass custom `--output` or `--replay-dir` values unle1ss there is a specific reason.
  Let the script generate the timestamped filename and bot-name pair under `.rep_bench/`.
- Command structure for the smoke benchmark:
  `source .venv/bin/activate`
  `python tools/run_representative_benchmark.py <bot_a> <bot_b> --maps default_small1.map26 default_medium1.map26 default_large1.map26 --seeds 1 --jobs 8`
- Command structure for the full representative benchmark:
  `source .venv/bin/activate`
  `python tools/run_representative_benchmark.py <bot_a> <bot_b> --seeds 1 --jobs 8`
- The benchmark tool swaps seats by default, so the generated run covers both `<bot_a> vs <bot_b>` and `<bot_b> vs <bot_a>`.

## Updating bots
- Use the README.md in each bot as a workspace for keeping track of changes, failures, and TODOs.
- Edit the README.md of the bot after every change with what you have added.
