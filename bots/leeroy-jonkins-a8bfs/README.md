# leeroy-jonkins-a8bfs

Hybrid bot combining leeroy-jonkins economic policy with jon-6-a8bfs assault system.

## Design

- **Economic bots** (cardinal spawns: N/S/E/W): Find ore, build harvesters, tile conveyor routes back to core. Uses leeroy-jonkins economic constants (MAX_BUILDER_COUNT=20).
- **Assault bots** (diagonal spawns: NE/NW/SE/SW): BFS-based assault system from jon-6-a8bfs. Scout enemy harvesters via symmetry prediction, navigate to ring positions, build sentinels to attack enemy logistics.
- **Sentinels**: Turrets built by assault bots. Use cluster-aware targeting from jon-6-a8bfs (prioritize turrets > core/logistics > other).

## Spawning

- Turns 0-3: 4 economy bots (cardinal directions, MIN_BUILDER_COUNT fill)
- Turns 4-7: 4 assault bots (diagonal directions, opening assault wave)
- After: Economy bots on 15-turn interval when titanium 500-2000, bonus assault bots when titanium >= 90

## Origin

- Economic policy (constants, MAX_BUILDER_COUNT=20): leeroy-jonkins
- Assault system (assault.py, mode_assaulting.py, sentinel_bot.py): jon-6-a8bfs
- Perception/navigation/marker/utils: jon-6-a8bfs (assault-compatible versions)
- Economic modes (mode_finding_ore, mode_tiling_back, mode_exploring, healing): jon-6-a8bfs versions (nearly identical to leeroy-jonkins, with assault-compatible perception)
