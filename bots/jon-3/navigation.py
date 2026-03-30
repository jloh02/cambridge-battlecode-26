import heapq
import utils
import time
from states import BuilderMode, ActionType
from cambc import Controller, Direction, Position, EntityType

CARDINAL_COST = 1.0
DEFAULT_COST = 1.0
BRIDGE_COST = 20.0

A_STAR_ITERATION_LIMIT = 200
A_STAR_TIME_LIMIT_NANOSECONDS = 1_000_000  # 1 ms

# Store raw (dx, dy) int tuples instead of Position objects — avoids object
# creation and attribute lookups in the hot loop.
BRIDGE_OFFSETS: list[tuple[tuple[int, int], float]] = []
for _dx in range(-3, 4):
    for _dy in range(-3, 4):
        _dist_sq = _dx * _dx + _dy * _dy
        if 1 < _dist_sq <= 9:
            BRIDGE_OFFSETS.append(((_dx, _dy), BRIDGE_COST))


def _heuristic(nx: int, ny: int, tx: int, ty: int, cardinal_only: bool) -> float:
    """
    Admissible heuristic.
    • cardinal_only  → Manhattan distance (tight; never over-estimates 1-step cost)
    • diagonal moves → Chebyshev distance
    Using the *correct* heuristic means A* expands far fewer nodes.
    """
    dx = abs(nx - tx)
    dy = abs(ny - ty)
    return (dx + dy) if cardinal_only else max(dx, dy)


def _get_move_deltas(cardinal_only: bool) -> list[tuple[tuple[int, int], float]]:
    """Returns (dx, dy) int pairs so the inner loop avoids Position.add() overhead."""
    dirs = utils.CARDINAL_DIRECTIONS if cardinal_only else utils.DIRECTIONS
    cost = CARDINAL_COST if cardinal_only else DEFAULT_COST
    return [
        (
            (int(Position(0, 0).add(d).x), int(Position(0, 0).add(d).y)),
            d,
            cost,
        )
        for d in dirs
    ]


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

    # came_from: (x, y) -> (parent_x, parent_y, action_tuple) | None for start
    came_from: dict[tuple[int, int], tuple | None] = {}
    g_costs: dict[tuple[int, int], float] = {}

    start_key = (sx, sy)
    came_from[start_key] = None
    g_costs[start_key] = 0.0

    # Heap entries: (f_cost, counter, x, y)
    # Storing raw ints avoids Position comparison overhead on tie-breaks.
    counter = 0
    open_set: list = []
    heapq.heappush(
        open_set, (_heuristic(sx, sy, tx, ty, cardinal_only), counter, sx, sy)
    )

    move_deltas = _CARDINAL_DELTAS if cardinal_only else _DIAGONAL_DELTAS
    tiling_back = bot.builder_mode == BuilderMode.TILING_BACK
    bot_grid = bot.grid  # local ref avoids repeated attribute lookups
    do_not_build = utils.DO_NOT_BUILD_ON

    iterations = 0
    found = False

    while open_set:
        if (time.time_ns() - start_time) >= A_STAR_TIME_LIMIT_NANOSECONDS:
            bot.logger.print(f"A* time limit reached after {iterations} iterations")
            break
        if iterations >= A_STAR_ITERATION_LIMIT:
            bot.logger.print(
                f"A* iteration limit reached after {iterations} iterations"
            )
            break

        _, _, cx, cy = heapq.heappop(open_set)
        current_key = (cx, cy)

        if cx == tx and cy == ty:
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

            # Inline is_disallowed_to_build_on — avoids function-call overhead
            # in the tightest loop in the code-base.
            nb_data = bot_grid.get(nb_key)
            if nb_data is not None:
                entv = nb_data.get("entity")
                if entv is not None and entv in do_not_build:
                    continue
                b_type = nb_data.get("building")
                if b_type is not None and b_type not in {
                    EntityType.ROAD,
                    EntityType.CONVEYOR,
                    EntityType.ARMOURED_CONVEYOR,
                    EntityType.MARKER,
                }:
                    continue

            new_g = current_g + cost
            if nb_key not in g_costs or new_g < g_costs[nb_key]:
                g_costs[nb_key] = new_g
                came_from[nb_key] = (cx, cy, (ActionType.CONVEYOR, direction))
                f = new_g + _heuristic(nx, ny, tx, ty, cardinal_only)
                counter += 1
                heapq.heappush(open_set, (f, counter, nx, ny))

        # ── 2. Bridge moves (tiling back only) ──────────────────────────────
        if allow_bridges and tiling_back:
            for (ddx, ddy), cost in BRIDGE_OFFSETS:
                nx, ny = cx + ddx, cy + ddy

                if not (0 <= nx < map_w and 0 <= ny < map_h):
                    continue

                nb_key = (nx, ny)
                if nb_key in known_obstacles:
                    continue

                nb_data = bot_grid.get(nb_key)
                if nb_data is not None:
                    entv = nb_data.get("entity")
                    if entv is not None and entv in do_not_build:
                        continue
                    b_type = nb_data.get("building")
                    if b_type is not None and b_type not in {
                        EntityType.ROAD,
                        EntityType.CONVEYOR,
                        EntityType.ARMOURED_CONVEYOR,
                        EntityType.MARKER,
                    }:
                        continue

                new_g = current_g + cost
                if nb_key not in g_costs or new_g < g_costs[nb_key]:
                    g_costs[nb_key] = new_g
                    bridge_target = Position(nx, ny)
                    came_from[nb_key] = (cx, cy, (ActionType.BRIDGE, bridge_target))
                    f = new_g + _heuristic(nx, ny, tx, ty, cardinal_only)
                    counter += 1
                    heapq.heappush(open_set, (f, counter, nx, ny))

    # ── Reconstruct path ─────────────────────────────────────────────────────
    goal_key = (tx, ty)

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
        _, _, bx, by = open_set[0]  # heapq[0] is always the smallest
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

    all_obstacles = state["known_obstacles"].union(set(active_temp_obs.keys()))

    # 2. Update obstacle memory from immediate neighbours
    for d in utils.DIRECTIONS:
        neighbor_pos = current_pos.add(d)
        if not utils.is_passable(ct, current_pos, d):
            state["known_obstacles"].add((neighbor_pos.x, neighbor_pos.y))

    # 3. Invalidate cached path if target changed
    target_tuple = (target_pos.x, target_pos.y)
    if state.get("current_target") != target_tuple:
        state["path"] = []
        state["current_target"] = target_tuple

    # 4. Validate the next step against current obstacles
    if state["path"]:
        next_type, next_val = state["path"][0]
        next_pos = (
            current_pos.add(next_val) if next_type == ActionType.CONVEYOR else next_val
        )
        if (next_pos.x, next_pos.y) in all_obstacles:
            state["path"] = []

    # 5. Recompute if empty
    if not state["path"]:
        state["path"] = calculate_astar_path(
            bot,
            ct,
            current_pos,
            target_pos,
            all_obstacles,
            cardinal_only=cardinal_only,
            throws_exception_on_failure=throws_exception_on_failure,
        )

    # 6. Pop the next step
    move_action = state["path"].pop(0) if state["path"] else None

    log_path(bot, ct, state["path"])
    bot.logger.log(f"Next move: {move_action}")

    return move_action, state


def log_path(bot, ct, path):
    if not path:
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

    # NOTE: removed the full known_obstacles log — printing a large set every
    # turn was itself a significant cost.

    move_action, new_state = compute_pathfinding_step(
        bot,
        ct,
        current_pos,
        target_pos,
        bot.pathfinding_state,
        cardinal_only,
        throws_exception_on_failure,
    )

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

    if bot.builder_mode != BuilderMode.TILING_BACK and ct.can_build_road(next_pos):
        ct.build_road(next_pos)

    # Execute move
    if move_dir is not None and ct.can_move(move_dir):
        ct.move(move_dir)
        bot.pathfinding_state = new_state
        return True, ct.get_position()

    # Stumped: if blocked by a friendly builder, add a temporary obstacle
    next_key = (next_pos.x, next_pos.y)
    grid_entry = bot.grid.get(next_key, {})
    if (
        grid_entry.get("entity") == EntityType.BUILDER_BOT
        and grid_entry.get("entity_team") == ct.get_team()
        and bot.builder_mode != BuilderMode.TILING_BACK
    ):
        other_bot_id = grid_entry.get("id")
        if (
            other_bot_id is not None and other_bot_id < ct.get_id()
        ) or _is_connected_to_conveyor(bot, ct, next_pos):
            bot.pathfinding_state.setdefault("temporary_obstacles", {})[next_key] = (
                ct.get_current_round() + 3
            )

    return False, current_pos


def move_towards(
    bot, ct: Controller, target_pos: Position, cardinal_only: bool = False
) -> bool:
    if ct.get_position() == target_pos:
        return True
    ct.draw_indicator_dot(target_pos, 0, 255, 0)
    try:
        try_pathfinding_move(
            bot, ct, target_pos, cardinal_only, throws_exception_on_failure=True
        )
    except Exception as e:
        bot.logger.print(f"Pathfinding error: {e}")
        return False
    return True


def _is_connected_to_conveyor(bot, ct: Controller, start_pos: Position) -> bool:
    """Traces conveyor chain backwards to verify it reaches a friendly conveyor or core."""
    current = start_pos
    visited: set[tuple[int, int]] = set()

    while current:
        pos_tuple = (current.x, current.y)

        if (
            utils.manhattan(current, bot.core_pos) <= 1
            or current in bot.known_friendly_conveyors
        ):
            return True

        if pos_tuple in visited:
            return False
        visited.add(pos_tuple)

        grid_data = bot.grid.get(pos_tuple, {})
        building = grid_data.get("building")

        if (
            building not in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}
            or grid_data.get("building_team") != ct.get_team()
        ):
            return False

        b_dir = grid_data.get("building_dir")
        if not b_dir:
            return False

        current = current.subtract(b_dir)

    return False
