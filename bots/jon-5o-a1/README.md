# jon-5o

Minimal `jon-5` derivative focused on reducing A* spikes without changing the
FSM or macro economy policy.

Patch baseline checked against the official 2026-03-30 / 2026-03-31 changelog
and local SDK `cambc 1.5.4`: starting Ti `500`, passive Ti `10` every `4`
rounds, builder base cost `30`, harvester base cost `20`, foundry base cost
`40`, armoured conveyor base cost `5`, bridge base cost `20`, bridge target
radius² `9`, and max team units `50`.

## Optimizations by AI
- Hard-cap pathfinding reliability under tight turn budgets
- Enemy-aware visible sensing now uses `get_nearby_units()` plus
  `get_nearby_buildings()` instead of re-enumerating all nearby entities
- Bounded A* with mode-aware time and iteration budgets
- Cached nearby controller metadata during perception refresh
- Prefix-trim path invalidation and greedy fallback movement
- Deferred bridge transit planning to avoid same-turn double A*
- Single-pass ore access-point selection and conveyor connectivity helpers
- Debug counters for A* cache hit/recompute/fallback analysis

## Departures From `jon-5`
- A* keeps the same heuristic family, but `jon-5o` breaks ties by lower raw
  target distance and then lower start-to-target line deviation.
- Full A* is now clamped by a soft per-turn builder deadline, with a bounded
  3-step micro-plan tried before falling back to greedy movement.
- Bridge expansion is stricter: clutter still enables bridge search, but most
  sideways/backwards bridge landings are filtered out unless they hit the exact
  target or a remembered connected friendly line.
- Macro policy is intentionally unchanged. Strategy-local penalties such as the
  bridge cost weight remain policy knobs, not SDK constants.

## TODO for jon-5

### AI
- [ ] Add map benchmark script to compare p50, p95, and p99 turn timing
- [ ] Tune mode budgets by map size and congestion
- [ ] Improve obstacle epoching for smarter cache reuse
- [ ] Add rating-regression checks alongside timeout checks

### Human
[ ] Build defense around harvesters
[ ] Heal core to defend rush strat
[ ] Reduce conveyor congestion by limiting number of tags to same conveyor
    [ ] Alternative, use splitter near core when crowded
[ ] Reduce duplicate work using markers (INCOMPLETE)
[ ] Axionite collection
[ ] Use barriers to cover ores
[ ] Surveyor mode for builder bots with nothing to do
    [ ] they will check flow lines and repair
    [ ] also check if flow lines require split into core
