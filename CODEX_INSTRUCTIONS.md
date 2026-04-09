# Codex Repo Instructions

This file is the governing SOP for Codex work in this repository.

Use it for durable workflow, validation policy, and promotion criteria. Use
`CODEX_SCRATCHPAD.md` only for active task memory when a long-form task is in
progress.

## 1. Repo Ground Truth

- `bots/<name>/` is the canonical source form of a bot.
- `.dist/bots/<name>/` is optional build output, not the source of truth.
- `cambc.toml` currently points at:
  - `bots`
  - `maps`
  - `replay.replay26`
- Prefer `CODEX_EXPLAINER.md` for current game rules, SDK notes, and repo
  architecture.
- Prefer this file for working norms, validation SOPs, KPI definitions, and
  promotion gates.

## 2. Long-Form Task Protocol

Only activate the long-form scratchpad workflow when a user request contains
the exact sentence:

`This is a long-form task.`

When that sentence appears:

1. re-read this file before substantive work
2. update `CODEX_SCRATCHPAD.md` with the active strategy name, task
   description, criteria, latest evidence, immediate next action, and a
   compaction-safe resume point
3. keep the scratchpad current until the task reaches a real stop condition

When that sentence does not appear:

- do not treat the scratchpad as an active project log
- keep durable SOPs and stable workflow notes here, not in the scratchpad

## 3. Tools Available In This Repo

Local environment and core tools:

- pyenv virtualenv: `cambc`
- CLI: `cambc` (`1.6.2` as last re-checked in repo docs)
- test runner: `pytest`
- shell utilities: standard terminal tools such as `rg`, `sed`, `git`, and
  repo-local Python entrypoints

Current `cambc` workflow to prefer:

- `cambc run`: local smoke checks with replay output
- `cambc watch`: open a local replay in the visualizer
- `cambc match test`: authoritative remote TLE-enforced test match for local
  bots
- `cambc match tests`: list remote test runs
- `cambc match replay`: download remote replay files
- `cambc match watch`: open a remote replay in the browser
- `cambc submission ...`: submission management

Repo-local helper scripts under `tools/`:

- `tools/analyze_replay.py`: replay decoding and summary metrics
- `tools/benchmark.py`: local benchmark helper
- `tools/benchmark_matrix.py`: pinned-opponent matrix benchmarking
- `tools/report.py`: summarize benchmark output
- `tools/promotion_gate.py`: promotion-gate helper
- `tools/build_bots.py`: optional clean bot bundle builder
- `tools/run_representative_benchmark.py`: representative benchmark runner
- `tools/review_match_with_openai.py`: match review helper

## 4. Development Workflow

When developing a bot, use this staged loop by default.
DO NOT STOP executing this loop until you have a clear reason to stop, such as:
- Achieving a promotion-worthy iteration
- Exhausting all reasonable hypotheses for improvement, even after giving them many chances for improvement and bug-fixing.

### Stage 1: change the bot

- Make the bot changes needed for the current hypothesis.
- Keep the edit set tight enough that failures remain explainable.

### Stage 2: add or update unit tests

- After each bot change, add or update basic unit tests that enforce the local
  contract the bot is supposed to satisfy in isolation.
- Run the most targeted pytest coverage first.
- Do not skip this stage just because later match results look good.

### Stage 3: `g16` smoke matches

After the targeted tests pass, run local smoke matches against the studied
opponent set.

Required shape:

- use `tools/benchmark_matrix.py`
- `16` games per opponent
- `8` games in each seat when the game count is even
- do not enforce a local time limit in this stage

Success condition:

- against each opponent individually, win at least `80%` of games

Typical command:

```bash
python tools/benchmark_matrix.py <candidate> <opponent_1> <opponent_2> --games-per-opponent 16
```

### Stage 4: `g64` tourney

If `g16` passes, run a larger local tournament against the same opponent set.

Required shape:

- use `tools/benchmark_matrix.py`
- `64` games per opponent
- balanced seat order
- enforce a local `2 ms` cap with `--tle-ms 2`

Important note:

- the real ladder budget is `2 ms` per round on AWS according to
  `CODEX_EXPLAINER.md`
- local `--tle-ms 2` is a useful filter, but remote `cambc match test` remains
  the final timing truth

Default success condition:

- unless the user specifies a different gate, use the same per-opponent
  `>= 80%` win-rate bar as `g16`
- record TLE pressure, TLE turns, and related timing stress as diagnostic
  evidence, not as an automatic failure by themselves
- if the iteration does fail later, timing pressure is a valid failure-mode
  explanation to cite during replay analysis

Typical command:

```bash
python tools/benchmark_matrix.py <candidate> <opponent_1> <opponent_2> --games-per-opponent 64 --tle-ms 2
```

### Stage 5: remote seat-paired validation

If `g64` passes, run remote tests against each opponent.

Required shape:

- use `cambc match test`
- run `2` remote matches per opponent
- run `1` match in each seat order

Success condition:

- for each remote match, the candidate should win by at least a `4-1` game
  margin regardless of seat order

### Stage 6: failure analysis and iteration decision

If any stage fails:

1. inspect the failure mode rather than treating the whole iteration as dead
2. if the failing stage was remote, download or analyze the remote replay via
   the API-backed tooling
3. analyze relevant replays with `tools/analyze_replay.py`
4. determine whether the current iteration is still an improvement over the
   previous one
5. determine whether the current stage still contains fixable bugs or workflow
   issues that block a fair evaluation

Decision rule after analysis:

- if the iteration shows real improvement, commit it even if further work is
  still needed
- if the changes are not worth keeping, roll them back
- if the changes are promising but not yet clean, keep fixing bugs
- after that decision, restart from Stage 1 with the next iteration

### Stage 7: success handling

If the staged workflow succeeds, commit the current iteration.

### Practical validation norms

- Check both seat orders before claiming improvement.
- Inspect the worst failures, not just aggregate summaries.
- Judge changes by objective metrics and replay evidence, not by headline win
  rate alone.
- Prefer traceable evidence tied to report files, replay files, or remote match
  ids.
- Keep changes small enough that rollback is cheap when the hypothesis fails.

## 5. Replay Review SOP

Replay evidence is first-class in this repo.

- `print()` output is recorded in the replay.
- Indicator lines and dots are replay-visible.
- Prefer traceable evidence tied to a replay file or remote match id.
- Keep remote replay downloads bounded: at most `10` games at once unless there
  is a strong reason to do more.
- Use local replay review to explain why a result changed, not just whether it
  changed.

Useful commands:

```bash
python tools/analyze_replay.py --replay-file replay.replay26
python tools/analyze_replay.py --match-id <match_id>
python tools/analyze_replay.py --latest-team-matches --limit 3
```

Useful related commands:

```bash
~/.pyenv/versions/cambc/bin/cambc watch replay.replay26
~/.pyenv/versions/cambc/bin/cambc match replay <match_id>
~/.pyenv/versions/cambc/bin/cambc match watch <match_id>
```

## 6. KPI Policy

The repo should track both delivered outcomes and mined or collected
diagnostics.

Primary KPI: `TiEq`

`TiEq = delivered_titanium + 4 * delivered_refined_axionite + early_win_bonus`

where:

- `early_win_bonus = 100000` if the bot wins before turn `2000`
- otherwise `early_win_bonus = 0`

Important note:

- `TiEq` is based on what is actually delivered to the core
- mined or collected totals are useful diagnostics, but they are not the KPI

Secondary diagnostics to retain when possible:

- mined titanium
- mined axionite
- delivered titanium
- delivered refined axionite
- harvesters alive
- stored titanium
- stored axionite
- stall or loop signals from replay analysis

## 7. Promotion Rule

A bot is promotion-worthy against a studied opponent set if and only if, for
every opponent in the set, it satisfies all of the following over `32` games:

- random map
- random seat
- random seed
- win rate `>= 80%`
- average `TiEq >= 100000`
- worst-game `TiEq >= 50000`

This is an all-opponents gate, not an aggregate-only gate. One weak matchup
fails promotion.

## 8. Current Strategic Baseline

The current repo baseline is still economy-first, with `jon-5` as the clearest
reference point for that style.

At a high level, the bot line tries to:

1. spawn enough builders to establish an early economy
2. find nearby titanium quickly
3. place harvesters once adjacent to ore
4. tile a working return path back to the core or an already-connected friendly
   logistics line
5. repeat without burning excessive turn budget on unbounded search

The important design principles worth preserving are:

- bounded pathfinding
- path caching and partial reuse
- preference for connecting into known friendly logistics
- judging success by delivered throughput, not mined totals alone

Current improvement directions still worth carrying forward:

- restore useful marker coordination
- add a real axionite foundry-plus-convert plan
- improve congestion handling
- add more intentional defense and survival behavior
- migrate strong tactics onto cleaner primitives incrementally rather than
  throwing away working behavior
