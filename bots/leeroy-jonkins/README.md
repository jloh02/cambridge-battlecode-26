# Leeroy Jonkins

Building on the basis of `jon-6`, `leeroy-jonkins` adds pipeline hijacks and early-rush cheese strategies in order to secure quick wins against unprepared opponents.

## Features
- Explicit pipeline hijack module (rather than implicit in TILING_BACK)
- Early rush strategy with 2 builder -> 2 rush bots who discover the enemy core and leverage nearby harvesters to quickly attack it.
  - The intent is to catch opponents off-guard.
  - As evidenced by strategies like jon-6, this need not work with even rudimentary defences + a solid economy.
  - Once the turret is built, rush bots return to normal, boosting the economy moving into mid- and late-game.

## TODO for leeroy-jonkins
[ ] Include cases where no enemy harvesters / ore deposits are in range of the enemy core (i.e. the rush bots need to establish a more robust offense pipeline to the enemy core)
[ ] Refactor to streamline with old pipeline overwrite
[?] Heal core to defend rush strat (kinda done with the bottom point)
  [x] Heal nearby entities that are being attacked
[ ] Build defense around harvesters
  [ ] Use barriers to cover ores
[x] Reduce conveyor congestion by limiting number of tags to same conveyor
  [ ] Tune more
[ ] Axionite collection
[ ] Reduce duplicate work using markers (INCOMPLETE)
[ ] Surveyor mode for builder bots with nothing to do
    [ ] they will check flow lines and repair
    [ ] also check if flow lines require split into core
