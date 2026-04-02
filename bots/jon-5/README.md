# jon-5

Model number 5 from @jloh02

## Optimizations by AI
- Hard-cap pathfinding reliability under tight turn budgets
- Incremental perception updates (no full-grid inference every turn)
- Bounded A* with mode-aware time and iteration budgets
- Prefix-trim path invalidation and greedy fallback movement
- Deferred bridge transit planning to avoid same-turn double A*
- Debug counters for A* cache hit/recompute/fallback analysis

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