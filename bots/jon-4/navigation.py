import heapq
import utils
import time
from states import BuilderMode, ActionType
from cambc import Controller, Position, EntityType, Environment

CARDINAL_COST = 1.0
DEFAULT_COST = 1.0
ROAD_BUILD_PENALTY = 1.5
BRIDGE_COST = 100.0  # Massive penalty; +10% global scaling ruins economies!
SNAP_LINE_MULTIPLIER = 0.1  # Heavily reward merging into existing friendly lines
WRONG_DIRECTION_CONVEYOR_PENALTY = (
    200.0  # Make tearing up existing lines completely forbidden
)

DEBUG_PATH_LOGGING = utils.DEBUG

# route passable buildings
PASSABLE_BUILDINGS = {
    EntityType.ROAD,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.MARKER,
}

A_STAR_ITERATION_LIMIT = 200
A_STAR_TIME_LIMIT_NANOSECONDS = 500_000
A_STAR_LOOKAHEAD_CANCEL = 5

# Store raw (dx, dy) int tuples instead of Position objects — avoids object
# creation and attribute lookups in the hot loop.
BRIDGE_OFFSETS: list[tuple[tuple[int, int], float]] = []
for _dx in range(-3, 4):
    for _dy in range(-3, 4):
        _dist_sq = _dx * _dx + _dy * _dy
        if 5 <= _dist_sq <= 9:
            BRIDGE_OFFSETS.append(((_dx, _dy), BRIDGE_COST))


def _heuristic(
    nx: int, ny: int, tx: int, ty: int, cardinal_only: bool, multiplier: float = 1.0
) -> float:
    """
    Admissible heuristic.
    • cardinal_only  → Manhattan distance (tight; never over-estimates 1-step cost)
    • diagonal moves → Chebyshev distance
    Using the *correct* heuristic means A* expands far fewer nodes.
    """
    dx = abs(nx - tx)
    dy = abs(ny - ty)
    base_dist = (dx + dy) if cardinal_only else max(dx, dy)
    return base_dist * multiplier


def _get_move_deltas(cardinal_only: bool) -> list[tuple[tuple[int, int], float]]:
    """Returns (dx, dy) int pairs so the inner loop avoids Position.add() overhead."""
    dirs = utils.CARDINAL_DIRECTIONS if cardinal_only else utils.DIRECTIONS
    cost = CARDINAL_COST if cardinal_only else DEFAULT_COST
    deltas = []
    for d in dirs:
        dx, dy = d.delta()
        deltas.append(((dx, dy), d, cost))
    return deltas


def _step_cost(
    nb_data: dict | None,
    base_cost: float,
    tiling_back: bool,
    move_dir=None,
    my_team=None,
    is_target=False,  # <-- Add this flag
) -> float:
    if nb_data is None:
        return base_cost

    b_type = nb_data.get("building")
    if b_type is None:
        return base_cost

    # Tiling back: penalize destroying friendly lines, reward using them
    if tiling_back:
        if b_type in {
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.BRIDGE,
        }:
            if nb_data.get("building_team") == my_team:
                # If it's our final destination, snap to it regardless of direction
                if (
                    is_target
                    or b_type == EntityType.BRIDGE
                    or nb_data.get("building_dir") == move_dir
                ):
                    return base_cost * SNAP_LINE_MULTIPLIER
                else:
                    return base_cost + WRONG_DIRECTION_CONVEYOR_PENALTY
        return base_cost

    # Normal movement
    if b_type in {
        EntityType.ROAD,
        EntityType.CONVEYOR,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.MARKER,
    }:
        return base_cost

    return base_cost + ROAD_BUILD_PENALTY


# Pre-build delta tables once at module load so calculate_astar_path never
# rebuilds them per call.
_CARDINAL_DELTAS = _get_move_deltas(cardinal_only=True)  # [(delta_xy, Direction, cost)]
_DIAGONAL_DELTAS = _get_move_deltas(cardinal_only=False)


def calculate_astar_path(
    bot,
    ct: Controller,
    start: Position,
    target: Position,
    known_obstacles: set[tuple[int, int]],
    cardinal_only: bool = False,
    allow_bridges: bool = True,
    throws_exception_on_failure: bool = False,
) -> list:
    """
    A* from start to target.

    KEY CHANGE — parent-pointer reconstruction instead of path-in-node:
    The old code did `new_path = list(path); new_path.append(step)` on every
    heap push, causing O(N²) total list copies for a path of length N.
    Now each node stores only its own (x, y) and the action that reached it;
    the full path is reconstructed in O(N) at the end.
    """
    start_time = time.time_ns()

    # Cache map bounds once — avoids two method calls per neighbor.
    map_w = ct.get_map_width()
    map_h = ct.get_map_height()

    sx, sy = start.x, start.y
    tx, ty = target.x, target.y
    target_key = (tx, ty)

    # came_from: (x, y) -> (parent_x, parent_y, action_tuple) | None for start
    came_from: dict[tuple[int, int], tuple | None] = {}
    g_costs: dict[tuple[int, int], float] = {}

    start_key = (sx, sy)
    came_from[start_key] = None
    g_costs[start_key] = 0.0

    move_deltas = _CARDINAL_DELTAS if cardinal_only else _DIAGONAL_DELTAS
    tiling_back = bot.builder_mode == BuilderMode.TILING_BACK
    h_mult = 1.0 if tiling_back else (1.0 + ROAD_BUILD_PENALTY)
    bot_grid = bot.grid  # local ref avoids repeated attribute lookups
    passable_buildings = PASSABLE_BUILDINGS
    my_team = ct.get_team()

    # Heap entries: (f_cost, g_cost, counter, x, y)
    # Including g_cost lets us cheaply skip stale heap entries.
    counter = 0
    open_set: list = []
    heapq.heappush(
        open_set,
        (_heuristic(sx, sy, tx, ty, cardinal_only, h_mult), 0.0, counter, sx, sy),
    )

    iterations = 0
    found = False

    while open_set:
        if (time.time_ns() - start_time) >= A_STAR_TIME_LIMIT_NANOSECONDS:
            break
        if iterations >= A_STAR_ITERATION_LIMIT:
            break

        _, popped_g, _, cx, cy = heapq.heappop(open_set)
        current_key = (cx, cy)
        if popped_g != g_costs.get(current_key):
            continue

        if current_key == target_key:
            found = True
            break

        iterations += 1
        current_g = g_costs[current_key]

        # ── 1. Cardinal / diagonal conveyor moves ───────────────────────────
        for (ddx, ddy), direction, cost in move_deltas:
            nx, ny = cx + ddx, cy + ddy

            if not (0 <= nx < map_w and 0 <= ny < map_h):
                continue

            nb_key = (nx, ny)
            if nb_key in known_obstacles:
                continue

            # Inline is_disallowed_to_build_on
            nb_data = bot_grid.get(nb_key)
            if nb_data is not None:
                nb_env = nb_data.get("env")
                if nb_env in {
                    Environment.WALL,
                    Environment.ORE_TITANIUM,
                    Environment.ORE_AXIONITE,
                }:
                    continue

                b_type = nb_data.get("building")
                if b_type is not None and b_type not in passable_buildings:
                    if nb_key != target_key:
                        continue

            # Pass whether this neighbor is the target
            is_target = nb_key == target_key
            new_g = current_g + _step_cost(
                nb_data, cost, tiling_back, direction, my_team, is_target
            )

            if nb_key not in g_costs or new_g < g_costs[nb_key]:
                g_costs[nb_key] = new_g
                came_from[nb_key] = (cx, cy, (ActionType.CONVEYOR, direction))
                f = new_g + _heuristic(nx, ny, tx, ty, cardinal_only, h_mult)
                counter += 1
                heapq.heappush(open_set, (f, new_g, counter, nx, ny))

        # 2. Bridge moves (tiling back only)
        if allow_bridges and tiling_back:
            # --- PRUNING: Prevent State Explosion ---
            # Only branch into bridge calculations if we are actually near clutter.
            # If the immediate area is completely open/empty, skip bridge math.
            needs_bridge = False

            # 1. Check current tile
            current_data = bot_grid.get(current_key)
            if current_data and current_data.get("building") not in {
                None,
                EntityType.ROAD,
                EntityType.MARKER,
            }:
                needs_bridge = True

            # 2. Check immediate neighbors
            if not needs_bridge:
                for (ddx, ddy), _, _ in _CARDINAL_DELTAS:
                    check_key = (cx + ddx, cy + ddy)

                    # If it's a hard obstacle (wall, ore, enemy core)
                    if check_key in known_obstacles:
                        needs_bridge = True
                        break

                    # If it's a building/conveyor (even a friendly passable one)
                    check_data = bot_grid.get(check_key)
                    if check_data is not None:
                        b_type = check_data.get("building")
                        if b_type not in {None, EntityType.ROAD, EntityType.MARKER}:
                            needs_bridge = True
                            break

            # 3. Only calculate bridge offsets if the area is congested
            if needs_bridge:
                for (ddx, ddy), cost in BRIDGE_OFFSETS:
                    nx, ny = cx + ddx, cy + ddy

                    if not (0 <= nx < map_w and 0 <= ny < map_h):
                        continue

                    nb_key = (nx, ny)
                    if nb_key in known_obstacles:
                        continue

                    nb_data = bot_grid.get(nb_key)
                    if nb_data is not None:
                        nb_env = nb_data.get("env")
                        if nb_env in {
                            Environment.WALL,
                            Environment.ORE_TITANIUM,
                            Environment.ORE_AXIONITE,
                        }:
                            continue

                        b_type = nb_data.get("building")
                        if b_type is not None and b_type not in passable_buildings:
                            if nb_key != target_key:
                                continue

                    new_g = current_g + cost
                    if nb_key not in g_costs or new_g < g_costs[nb_key]:
                        g_costs[nb_key] = new_g
                        bridge_target = Position(nx, ny)
                        came_from[nb_key] = (cx, cy, (ActionType.BRIDGE, bridge_target))
                        f = new_g + _heuristic(nx, ny, tx, ty, cardinal_only, h_mult)
                        counter += 1
                        heapq.heappush(open_set, (f, new_g, counter, nx, ny))

    goal_key = target_key

    if not found:
        ct.draw_indicator_dot(start, 255, 165, 0)
        msg = f"A* failed after {iterations} iterations"
        if throws_exception_on_failure:
            raise Exception(msg)
        bot.logger.print(msg)

        if not open_set:
            return []

        # Best-effort: back-track from the open-set node with the lowest f-cost.
        # It's the node closest to the goal we managed to reach.
        _, _, _, bx, by = open_set[0]  # heapq[0] is always the smallest
        goal_key = (bx, by)

    # Walk the came_from chain and reverse.
    path: list = []
    key = goal_key
    while came_from.get(key) is not None:
        px, py, action = came_from[key]
        path.append(action)
        key = (px, py)
    path.reverse()
    return path


def compute_pathfinding_step(
    bot,
    ct: Controller,
    current_pos: Position,
    target_pos: Position,
    current_state: dict,
    cardinal_only: bool = False,
    throws_exception_on_failure: bool = False,
) -> tuple:
    state = current_state.copy()
    state["path"] = list(state["path"])

    # 1. Expire temporary obstacles
    active_temp_obs = {
        pos: expiry
        for pos, expiry in state.get("temporary_obstacles", {}).items()
        if expiry > ct.get_current_round()
    }
    state["temporary_obstacles"] = active_temp_obs

    # # 2. Update obstacle memory from immediate neighbours
    for d in utils.DIRECTIONS:
        neighbor_pos = current_pos.add(d)
        if not utils.is_passable(bot, ct, current_pos, d):
            state["known_obstacles"].add((neighbor_pos.x, neighbor_pos.y))

    # 3. Invalidate cached path if target changed
    target_tuple = (target_pos.x, target_pos.y)
    if state.get("current_target") != target_tuple:
        state["path"] = []
        state["current_target"] = target_tuple

    # 4. Validate the next few steps against current obstacles
    if state["path"]:
        simulated_pos = current_pos
        for next_type, next_val in state["path"][:A_STAR_LOOKAHEAD_CANCEL]:
            simulated_pos = (
                simulated_pos.add(next_val)
                if next_type == ActionType.CONVEYOR
                else next_val
            )
            pos_key = (simulated_pos.x, simulated_pos.y)
            if pos_key in state["known_obstacles"] or pos_key in active_temp_obs:
                if (
                    pos_key != target_tuple
                ):  # Do not invalidate if the obstacle IS our target!
                    state["path"] = []
                    break

    # 5. Recompute if empty
    if not state["path"]:
        # Discard the target from obstacles so A* doesn't instantly block it
        combined_obs = state["known_obstacles"].union(active_temp_obs.keys())
        combined_obs.discard(target_tuple)

        state["path"] = calculate_astar_path(
            bot,
            ct,
            current_pos,
            target_pos,
            combined_obs,
            cardinal_only=cardinal_only,
            throws_exception_on_failure=throws_exception_on_failure,
        )

    # 6. Get the next step; optionally consume it
    log_path(bot, ct, state["path"])
    move_action = state["path"][0] if state["path"] else None

    return move_action, state


def log_path(bot, ct, path):
    if not DEBUG_PATH_LOGGING or not path:
        return
    path_coords = []
    current_pos = ct.get_position()
    for action_type, action_val in path:
        if action_type == ActionType.CONVEYOR:
            current_pos = current_pos.add(action_val)
        else:
            current_pos = action_val
        path_coords.append(f"{action_type}({current_pos.x},{current_pos.y})")
    bot.logger.log(f"Computed Path: {' -> '.join(path_coords)}")


def try_pathfinding_move(
    bot,
    ct: Controller,
    target_pos: Position,
    cardinal_only: bool = False,
    throws_exception_on_failure: bool = False,
) -> tuple[bool, Position]:
    """
    Executes one move step and updates memory.
    Returns (success, current_position).
    """
    current_pos = ct.get_position()

    move_action, new_state = compute_pathfinding_step(
        bot,
        ct,
        current_pos,
        target_pos,
        bot.pathfinding_state,
        cardinal_only,
        throws_exception_on_failure,
    )
    bot.pathfinding_state = new_state

    if move_action is None:
        return False, current_pos

    action_type, action_val = move_action

    # Resolve next_pos and move_dir regardless of action type, so neither is
    # ever unbound below (was a latent NameError in the original code).
    if action_type == ActionType.BRIDGE:
        next_pos = action_val
        move_dir = None
    else:
        move_dir = action_val
        next_pos = current_pos.add(action_val)

    if bot.builder_mode != BuilderMode.TILING_BACK:
        utils.destroy_marker_if_present(ct, next_pos)
        if ct.can_build_road(next_pos):
            ct.build_road(next_pos)

    # Execute move
    if move_dir is not None and ct.can_move(move_dir):
        ct.move(move_dir)
        if bot.pathfinding_state["path"]:
            bot.pathfinding_state["path"].pop(0)
        return True, ct.get_position()

    # Stumped: if blocked by a friendly builder, add a temporary obstacle
    next_key = (next_pos.x, next_pos.y)
    grid_entry = bot.grid.get(next_key, {})
    if (
        grid_entry.get("entity") == EntityType.BUILDER_BOT
        and grid_entry.get("entity_team") == ct.get_team()
        # and bot.builder_mode != BuilderMode.TILING_BACK # implicitly we aren't tiling back
    ):
        other_bot_id = grid_entry.get("id")
        bot.logger.log(
            f"Blocked by friendly builder bot at {next_pos}, id {other_bot_id}, _is_connected_to_harvester { _is_connected_to_harvester(bot, ct, next_pos) }"
        )
        if (
            other_bot_id is not None and other_bot_id < ct.get_id()
        ) or _is_connected_to_harvester(bot, ct, next_pos):
            bot.pathfinding_state.setdefault("temporary_obstacles", {})[next_key] = (
                ct.get_current_round() + 3
            )

    return False, current_pos


def move_towards(
    bot, ct: Controller, target_pos: Position, cardinal_only: bool = False
) -> bool:
    if ct.get_position() == target_pos:
        return True
    moved, _ = try_pathfinding_move(
        bot, ct, target_pos, cardinal_only, throws_exception_on_failure=False
    )
    ct.draw_indicator_line(ct.get_position(), target_pos, 0, 255, 0)
    return moved


def _is_connected_to_harvester(bot, ct: Controller, start_pos: Position) -> bool:
    """Reverse trace conveyors to see if we're connected to a harvester (and thus can safely ignore it as an obstacle)."""
    visited = set()
    to_visit = [start_pos]

    while to_visit:
        pos = to_visit.pop()
        if (pos.x, pos.y) in visited:
            continue
        visited.add((pos.x, pos.y))

        grid_entry = bot.grid.get((pos.x, pos.y), {})
        if grid_entry.get("entity") == EntityType.HARVESTER:
            return True

        for d in utils.CARDINAL_DIRECTIONS:
            neighbor_pos = pos.add(d)
            neighbor_entry = bot.grid.get((neighbor_pos.x, neighbor_pos.y), {})
            if neighbor_entry.get("building") == EntityType.HARVESTER:
                return True
            if (
                neighbor_entry.get("building")
                in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}
                and neighbor_entry.get("building_team") == ct.get_team()
            ):
                to_visit.append(neighbor_pos)

    return False
