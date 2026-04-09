# got-any-grapes

`got-any-grapes` is the live source bot in this directory.

The detailed behavior reference is in `EXPLAINER.md`. The short version:

- no active rush mode
- titanium-first economy
- diagonal spawn-slot builders open in assault mode
- non-assault builders prioritize ore, tile-back logistics, exploration, and opportunistic hijacks
- routing stays pure A* with resumable planner state and shared no-progress recovery

This file is intentionally brief so it does not drift separately from the bot explainer.
