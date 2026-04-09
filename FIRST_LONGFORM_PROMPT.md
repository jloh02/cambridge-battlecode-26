This is a long-form task.

Work on improving `got-any-grapes` in this repository.

Before doing substantive work:
- read `CODEX_INSTRUCTIONS.md`
- read `CODEX_EXPLAINER.md`
- read `CODEX_SCRATCHPAD.md` if it exists; otherwise create it

Use those files as follows:
- `CODEX_INSTRUCTIONS.md` is the governing SOP for workflow, validation stages, KPI policy, replay-review norms, and promotion criteria
- `CODEX_EXPLAINER.md` is the standing reference for current game rules, SDK/API reality, repo architecture, and background/context
- `CODEX_SCRATCHPAD.md` is the active task-memory file for this specific long-form effort only

Do not restate, paraphrase, or duplicate foundational guidance already covered by `CODEX_INSTRUCTIONS.md` or `CODEX_EXPLAINER.md` unless a specific correction is required.
Do not invent alternate workflow or promotion rules when the standing docs already define them.
Use the scratchpad to preserve continuity across compactions and iteration cycles.

Keep `CODEX_SCRATCHPAD.md` current with:
- active strategy name
- task description
- criteria
- latest evidence
- immediate next action
- a compaction-safe resume point

Task objective:
Improve `got-any-grapes` from its current low-floor, tiebreak-heavy state into a stable promotion candidate by fixing the main floor failures first, reconciling stale strategy/doc drift, and validating improvements using the repository’s existing SOP.

Task-specific plan:

1. Reconcile docs and live behavior
- inspect the live `got-any-grapes` code and current measured behavior.
- update `bots/got-any-grapes/EXPLAINER.md` with the most up-to-date behaviors of the strategy.
- update `CODEX_EXPLAINER.md` only where necessary so it reflects any relevant docs/CLI drift
- prefer live code plus measured results over stale README or stale scratchpad claims when describing bot behavior

2. Remove strategy drift before adding new behavior
- identify and quarantine or delete rush-only codepaths if they are truly inactive or impossible
- keep the live doctrine limited to what the bot actually uses unless a removed path is deliberately reintroduced with real call sites and tests
- after behavior work lands, clean up stale bot-specific docs so they match reality

3. Fix the mechanistic floor first
- prioritize builder loop / stall / no-progress failures on bad maps
- add one shared stuck/loop recovery policy across the relevant builder modes
- preserve the current timing substrate while removing stale-state and no-progress pathologies

4. Navigation constraints for this task
- keep routing purely A*-driven
- do not add a greedy fallback
- treat anytime-return A* as a last resort, not the routine mode
- replace split exact/resume behavior with one persistent A* engine that can resume the same search across turns
- make planner state persistent instead of repeatedly deep-copying or restarting equivalent searches
- optimize hot-loop ranking so it does not reconstruct full paths unnecessarily
- preserve the existing macro routing policy
- do not do a broad pathfinding rewrite beyond persistent pure-A* continuation and hot-loop optimization
- keep costs, heuristics, tie-break order, and bridge policy unchanged unless a concrete regression forces adjustment

5. Make offense adaptive rather than permanently overcommitted
- keep the useful assault ideas
- make assault commitment expire or fall back when no real opening appears
- do not commit extra assault units based only on raw titanium
- require a real offensive opportunity plus a healthy enough economy before deeper offensive commitment
- preserve opportunistic hijack where it creates value, but let it yield back into economy when it does not

6. Keep resource policy honest
- treat the live bot as titanium-first until a real foundry-plus-convert path exists
- do not enable mixed-ore collection in isolation
- only enable mixed-ore when foundry placement, conversion routing, and convert policy exist together
- keep docs honest about the current live resource policy

7. Validate using the repository’s existing workflow
- follow the staged test / benchmark / remote-validation loop defined in `CODEX_INSTRUCTIONS.md`
- add or update focused pytest coverage for new local contracts
- inspect replay evidence on the worst failures, not just aggregate summaries
- use the repo’s KPI and promotion criteria rather than inventing new ones unless the task itself explicitly requires a stricter additional gate

Studied opponents and especially relevant local scenarios for this task:
- opponents: `jon-6-a9bfs-surround`, `jon-6`, `leeroy-jonkins`
- collapse maps to inspect carefully: `bar_chart`, `starry_night`, `default_large1`, `default_large2`
- preserve-closeout maps to avoid regressing: `arena`, `galaxy`
DISCLAIMER: You should not use collapse maps and preserve-closeout maps to supplant smoke tests; only to diagnose failures.

Non-negotiable task-specific constraints:
- preserve the TLE-clean substrate
- no broad rewrite outside the scoped changes above
- no greedy fallback in routing
- no mixed-ore without the full conversion chain
- do not claim completion because one iteration looked good
- do not let compaction reset the task

When choosing the next action:
- prefer the highest-leverage change that most directly improves promotion viability
- prefer removing dead or stale behavior before layering on new behavior
- prefer the smallest validating test that can falsify the current hypothesis
- prefer replay-backed diagnosis over intuition when results conflict

At the end of each iteration:
- update `CODEX_SCRATCHPAD.md`
- record what changed
- record what was tested
- record what was observed
- record whether the change should be kept, fixed further, or rolled back
- record the exact next action

Only stop when:
- the task reaches a real stop condition under the repository workflow and this improvement effort is genuinely complete, or
- there is a concrete external blocker that cannot be resolved in-repo and it is documented clearly in `CODEX_SCRATCHPAD.md`