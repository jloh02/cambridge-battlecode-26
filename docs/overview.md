```markdown
# Cambridge Battlecode – Game Overview

## Objective
Collect resources and **destroy the enemy's core**.

To do this, you must:
- Find ore deposits
- Build harvesters
- Deliver resources back to the core via conveyors
- Expand your territory

---

## Win Conditions
If both cores survive after **2000 rounds**, the winner is decided by tiebreakers (in order):

1. **Axionite delivered** – total refined axionite delivered to the core
2. **Titanium delivered** – total titanium delivered to the core
3. **Harvesters alive** – number of harvesters currently alive
4. **Axionite stored** – total axionite currently stored
5. **Titanium stored** – total titanium currently stored
6. **Coinflip** – random tiebreaker

---

## Map
- Rectangular grid, **20×20 to 50×50** inclusive
- Origin `(0, 0)` is the top-left (northwest) corner
- Guaranteed to be **symmetric** by either reflection or rotation

Each grid cell is one of:

| Cell Type     | Description                        |
|---------------|------------------------------------|
| Empty         | Can build anything                 |
| Wall          | Impassable, cannot build           |
| Titanium ore  | Harvesters mine titanium           |
| Axionite ore  | Harvesters mine raw axionite       |

Walls prevent building anything on the tile they occupy. Ores are tiles on which harvesters may be built to mine resources.

---

## Units
Units are game entities that run an **independent instance** of your submitted code. The core, builder bots, and turrets are units. **Harvesters are not units** — they operate automatically.

Each round, units take their turns **in the order they were spawned**. After all units have taken their turns, resources are distributed.

Each team can have at most **50 living units total**, including the core. In practice, that means a team can have at most **49 additional living units at once**. You can inspect the current count with `c.get_unit_count()`, and the cap is exposed as `GameConstants.MAX_TEAM_UNITS`.

### Vision & Action Radius

Units have a **vision radius** and an **action radius**.

- The **vision radius** is the area in which the unit can sense its environment.
- The **action radius** is the area in which the unit can perform actions, such as building, placing markers, or destroying buildings.

All units have an action radius of √2 (r² = 2), except the core, which has an action radius of √8 (r² = 8) measured from its centre.

Turrets also have an **attack range** which is different from their action radius.

| Unit         | Vision r² | Action r²        |
|--------------|-----------|------------------|
| Core         | 36        | 8 (from centre)  |
| Builder bot  | 20        | 2                |
| Gunner       | 13        | 2                |
| Sentinel     | 32        | 2                |
| Breach       | 10        | 2                |
| Launcher     | 26        | 2                |

Turrets also have a separate **attack range** distinct from their action radius.

### Cooldowns
All units have **action** and **move** cooldowns (non-negative integers, decrease by 1 at the end of each round).
Actions and movement can only be performed when the respective cooldown is **0**.

> The move cooldown is only used by the **builder bot** — it is the only mobile unit.

### Markers
All units may place **one marker per round** on a tile within action radius. This is separate from the action cooldown. You can overwrite an existing friendly marker, but not an enemy marker.

### Self-Destruct
All units may self-destruct at any time. Builder bots do **not** deal damage when they self-destruct.

---

## Buildings
Buildings are game entities that are **immovable**. All entities are buildings except builder bots.
In particular, the core and turrets are considered **both a unit and a building**.

---

## Entity IDs
All entities (buildings and units) have a **unique integer ID**. All **Controller** methods that deal with entities accept and return these IDs. Properties of an entity can be queried with getter functions — for example, `c.get_hp(id)`.

```python
# Get all nearby entities and check their type
for entity_id in c.get_nearby_entities():
    if c.get_entity_type(entity_id) == EntityType.HARVESTER:
        pos = c.get_position(entity_id)
```
## Resource IDs
Each stored resource stack also has a **unique integer ID**. Use these IDs when you want to tell otherwise identical stacks apart in your logistics network.

You can query the stack currently stored in a conveyor, splitter, armoured conveyor, bridge, or foundry with `c.get_stored_resource_id(id)`. If the building is empty, it returns `None`.

```python
resource_type = c.get_stored_resource(conveyor_id)
resource_id = c.get_stored_resource_id(conveyor_id)
```

---

## Computation Limit
Each unit gets **2ms of CPU time** per round

If exceeded, execution is interrupted and `run()` is called fresh on the next round - **your bot does not resume where it left off**. To absorb variance, each unit has an **extra time buffer** equal to 5% of the time limit. If a round takes longer than 2ms, the overage is deducted from the buffer. If a round takes less than 2ms, the savings are refunded to the buffer (capped at 5%).

Once a unit exhausts both its 2ms budget and its buffer in a single round, it is interrupted immediately.

Each bot process has a **1 GB memory limit**. Exceeding this will terminate the process.

Only Python standard library modules are available. External packages (e.g. `numpy`, `scipy`) cannot be imported — bots run in a sandboxed environment with no `pip install`.

> `cambc run` does **not** enforce time limits. Use `cambc test-run` to test on the same AWS
> Graviton3 hardware used for ladder matches.

---

## Debugging
- **stdout** via `print(msg)` is captured by the engine and saved to the replay. You can view each unit’s output in the visualiser.
- **stderr** prints to the console in real time — use this for debugging during local runs.
- `c.draw_indicator_line(pos_a, pos_b, r, g, b)` — draws a debug line overlay on the map, saved to the replay
- `c.draw_indicator_dot(pos, r, g, b)` — draws a debug dot overlay on the map, saved to the replay

---

## Key Concepts

**One Player instance per unit**

Each unit (core, builder bot, turret) gets its own `Player` instance. Instance variables persist across rounds for that unit, but are `not shared` between units. Use `markers` for inter-unit communication.

**The Controller object**

The `controller` argument passed to `run()` provides all game queries and actions. See the full Controller API reference.

**Imports from cambc**

`from cambc import *` gives you all game types: `Team`, `EntityType`, `Direction`, `Position`, `ResourceType`, `Environment`, `GameConstants`, `GameError`, and `Controller`.

**Time limit**

Each unit gets **2ms of CPU time** per round, plus a 5% buffer that refills when you use less. Locally there are no time limits — use remote test runs to check performance on the actual hardware.

**No external packages**

Only Python standard library modules are available. External packages like `numpy` or `scipy` cannot be imported — bots run in a sandboxed environment with no `pip install`.

