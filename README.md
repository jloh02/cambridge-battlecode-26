# Cambridge Battlecode 2026

https://battlecode.cam/

**Team:** ~~Cutie Fan Club~~ NUS Duck Robots

## Raw Replay Schema

This repo's tooling reads raw `.replay26` files through
[tools/replay_schema.py](/Users/n00bcak/programming/jloh-camb-battlecode/tools/replay_schema.py).
The useful human-level shape is:

- `Replay`
  - `map`: one `Map`
  - `turns[]`: ordered `Turn` records
  - `winner`: optional team enum
- `Map`
  - `width`, `height`
  - `rows[]`: tile environment rows
  - `cores[]`: core ids, teams, and centre positions
- `Turn`
  - `updates[]`: ordered state changes for that round
- `Update`
  - one variant per entry; the repo currently depends on:
    - `placeEntity`
    - `moveBuilderBot`
    - `removeEntity`
    - `distributeResources`
    - `updateHp`
    - `updatePlayers`
    - `setActionCooldown`
    - `setMoveCooldown`
    - `botOutput`
    - `indicatorLine`
    - `indicatorDot`
    - `fireTurret`
    - `builderAttack`
- `Entity`
  - base fields: `id`, `team`, `position`, `hp`, `maxHp`
  - plus exactly one typed payload such as `builderBot`, `conveyor`, `bridge`,
    `harvester`, `foundry`, `marker`, `core`, `gunner`, `sentinel`, `breach`,
    or `launcher`

Some especially useful payloads:

- `botOutput`: `id`, `stdout`, `execTimeUs`, `tled`
- `distributeResources.moves[]`: source tile, destination tile, optional
  resource id
- directional logistics/turret entities store facing direction in their typed
  payload
- bridges store their landing tile in the `bridge.target` payload
