import heapq
import utils
import time
from collections import deque
from states import BuilderMode, ActionType
from cambc import Controller, Position, EntityType, Environment, Direction

CARDINAL_COST = 1.0
DEFAULT_COST = 1.0
ROAD_BUILD_PENALTY = 1.0
BRIDGE_COST = 10.0
SNAP_LINE_MULTIPLIER = 0.3  # Heavily reward merging into existing friendly lines
WRONG_DIRECTION_CONVEYOR_PENALTY = (
    300.0  # Make tearing up existing lines completely forbidden
)
CONNECTED_CONVEYOR_LOAD_PENALTIES = [
    0.0,
    0.0,
    0.0,
    1.0,
    2.0,
    2.0,
    6.0,
    14.0,
    30.0,
    62.0,
]

DEBUG_PATH_LOGGING = utils.DEBUG

# route passable buildings
PASSABLE_BUILDINGS = {
    EntityType.ROAD,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.MARKER,
}
PASSABLE_ENTITIES = PASSABLE_BUILDINGS | {EntityType.CORE, EntityType.BUILDER_BOT}

TRANSPORT_BUILDINGS = {
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
}

IMPASSABLE_TILES = {
    Environment.WALL,
    Environment.ORE_TITANIUM,
    Environment.ORE_AXIONITE,
}

A_STAR_ITERATION_LIMIT = 200
A_STAR_TIME_LIMIT_NANOSECONDS = 500_000
A_STAR_LOOKAHEAD_CANCEL = 5
A_STAR_TIME_GUARD_NANOSECONDS = 80_000
MIN_A_STAR_RUNTIME_BUDGET_NANOSECONDS = 120_000
MICRO_PLAN_STEP_LIMIT = 3
MICRO_PLAN_TRIGGER_DISTANCE = 3
ANYTIME_ASTAR_ITERATION_DIVISOR = 2
ANYTIME_ASTAR_MIN_ITERATIONS = 48
SPECULATIVE_PATH_TRIGGER_LENGTH = 2
_EMPTY_BLOCKERS = frozenset()
SHARED_PROGRESS_STALL_LIMIT = 4
SHARED_PROGRESS_TTL = 12
SHARED_PROGRESS_MODES = {
    BuilderMode.FINDING_ORE,
    BuilderMode.EXPLORING,
    BuilderMode.TILING_BACK,
}

# Schema: BuilderMode -> (iteration_limit, time_limit_ns)
# TILING_BACK gets the largest budget because that is where route completion has
# the highest economic payoff; exploration gets the smallest budget because it
# is a fallback mode, not the main value engine.
_MODE_BUDGETS = {
    BuilderMode.TILING_BACK: (220, 450_000),
    BuilderMode.FINDING_ORE: (180, 350_000),
    BuilderMode.EXPLORING: (140, 260_000),
    BuilderMode.ASSAULTING: (150, 280_000),
}

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
    Heuristic estimating cost to go from (nx, ny) to (tx, ty).
    • cardinal_only  -> Manhattan (L1) distance (tight; never over-estimates 1-step cost)
    • diagonal moves -> Chebyshev (Linf) distance

    Multipliers <= 1.0 guarantee admissibility.
    Multipliers >= 1.0 improve speed at the cost of optimality.
    """
    dx = abs(nx - tx)
    dy = abs(ny - ty)
    base_dist = (dx + dy) if cardinal_only else max(dx, dy)
    return base_dist * multiplier


def _line_deviation_score(nx: int, ny: int, sx: int, sy: int, tx: int, ty: int) -> int:
    """Same strategy as `jon-5`, cheaper execution: integer line-deviation tiebreak."""
    return abs((tx - sx) * (sy - ny) - (sx - nx) * (ty - sy))


def _get_move_deltas(cardinal_only: bool) -> list[tuple[tuple[int, int], float]]:
    """Returns (dx, dy) int pairs so the inner loop avoids Position.add() overhead."""
    dirs = utils.CARDINAL_DIRECTIONS if cardinal_only else utils.DIRECTIONS
    cost = CARDINAL_COST if cardinal_only else DEFAULT_COST
    deltas = []
    for d in dirs:
        dx, dy = d.delta()
        deltas.append(((dx, dy), d, cost))
    return deltas


def connected_conveyor_load_penalty(load_count: int) -> float:
    if load_count <= 0:
        return 0.0
    if load_count < len(CONNECTED_CONVEYOR_LOAD_PENALTIES):
        return CONNECTED_CONVEYOR_LOAD_PENALTIES[load_count]
    extra_load = load_count - (len(CONNECTED_CONVEYOR_LOAD_PENALTIES) - 1)
    return CONNECTED_CONVEYOR_LOAD_PENALTIES[-1] * (2**extra_load)


def _step_cost(
    nb_data: dict | None,
    base_cost: float,
    tiling_back: bool,
    move_dir=None,
    my_team=None,
    is_target=False,  # <-- Add this flag
    connected_load=0,
) -> float:
    load_penalty = (
        connected_conveyor_load_penalty(connected_load)
        if tiling_back and is_target
        else 0.0
    )
    if nb_data is None:
        return base_cost + load_penalty

    b_type = nb_data.get("building")
    if b_type is None:
        return base_cost + load_penalty

    # Tiling back: penalize destroying friendly lines, reward using them
    if tiling_back:
        if b_type in TRANSPORT_BUILDINGS:
            if nb_data.get("building_team") == my_team:
                # If it's our final destination, snap to it regardless of direction
                if (
                    is_target
                    or b_type == EntityType.BRIDGE
                    or nb_data.get("building_dir") == move_dir
                ):
                    return base_cost * SNAP_LINE_MULTIPLIER + load_penalty
                else:
                    return base_cost + WRONG_DIRECTION_CONVEYOR_PENALTY
        return base_cost + load_penalty

    # Normal movement
    if b_type in PASSABLE_BUILDINGS:
        return base_cost + load_penalty

    return base_cost + ROAD_BUILD_PENALTY + load_penalty


# Pre-build delta tables once at module load,
# so calculate_astar_path never rebuilds them per call.
_CARDINAL_DELTAS = _get_move_deltas(cardinal_only=True)  # [(delta_xy, Direction, cost)]
_DIAGONAL_DELTAS = _get_move_deltas(cardinal_only=False)
ASSAULT_CLOCKWISE_DIRECTIONS = [
    Direction.NORTH,
    Direction.NORTHEAST,
    Direction.EAST,
    Direction.SOUTHEAST,
    Direction.SOUTH,
    Direction.SOUTHWEST,
    Direction.WEST,
    Direction.NORTHWEST,
]
ASSAULT_DIRECTION_INDEX = {
    direction: index for index, direction in enumerate(ASSAULT_CLOCKWISE_DIRECTIONS)
}
ASSAULT_DIRECTION_DELTAS = {
    direction: direction.delta() for direction in ASSAULT_CLOCKWISE_DIRECTIONS
}
ASSAULT_CLEARABLE_TARGET_BUILDINGS = {
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
}
MAX_BFS_NODES = 256
ASSAULT_TEMP_OBSTACLE_TTL = 5


def _bump_stat(bot, key: str, value: int = 1):
    stats = getattr(bot, "stats", None)
    if stats is not None:
        stats[key] = stats.get(key, 0) + value


def _get_astar_limits(bot) -> tuple[int, int]:
    mode = getattr(bot, "builder_mode", None)
    return _MODE_BUDGETS.get(
        mode, (A_STAR_ITERATION_LIMIT, A_STAR_TIME_LIMIT_NANOSECONDS)
    )


def get_available_astar_time_budget(bot, *, record_skip: bool = False) -> int:
    """Same strategy as `jon-5`, cheaper execution: clamp A* by remaining turn time."""
    _, mode_budget_ns = _get_astar_limits(bot)
    deadline_ns = getattr(bot, "turn_decision_deadline_ns", 0)
    if deadline_ns <= 0:
        return mode_budget_ns

    remaining_ns = deadline_ns - time.time_ns() - A_STAR_TIME_GUARD_NANOSECONDS
    if remaining_ns < MIN_A_STAR_RUNTIME_BUDGET_NANOSECONDS:
        if record_skip:
            _bump_stat(bot, "astar_budget_skips")
        return 0

    return min(mode_budget_ns, remaining_ns)


def _is_walkable_step(
    bot_grid: dict,
    nb_key: tuple[int, int],
    target_key: tuple[int, int],
    known_obstacles: set[tuple[int, int]],
    temporary_obstacles: set[tuple[int, int]],
    passable_buildings: set[EntityType],
) -> tuple[bool, dict | None]:
    if (
        nb_key in known_obstacles or nb_key in temporary_obstacles
    ) and nb_key != target_key:
        return False, None

    nb_data = bot_grid.get(nb_key)
    if nb_data is not None:
        nb_env = nb_data.get("env")
        if nb_env in IMPASSABLE_TILES:
            return False, nb_data

        b_type = nb_data.get("building")
        if (
            b_type is not None
            and b_type not in passable_buildings
            and nb_key != target_key
        ):
            return False, nb_data

    return True, nb_data


def _refresh_local_obstacle_memory(
    bot, current_pos: Position, known_obstacles: set[tuple[int, int]], my_team
):
    # Same strategy as `jon-5`, cheaper execution: refresh only the immediate
    # ring from the remembered grid instead of re-querying controller
    # passability for every neighbor on every turn.
    for d in utils.DIRECTIONS:
        neighbor_pos = current_pos.add(d)
        neighbor_key = (neighbor_pos.x, neighbor_pos.y)
        tile_data = bot.grid.get(neighbor_key)
        if tile_data is None:
            continue

        env = tile_data.get("env")
        entity = tile_data.get("entity")
        building = tile_data.get("building")
        blocked = False

        if env in IMPASSABLE_TILES:
            blocked = True
        elif entity == EntityType.HARVESTER or building == EntityType.HARVESTER:
            blocked = True
        elif entity == EntityType.CORE and tile_data.get("entity_team") != my_team:
            blocked = True
        elif entity is not None and entity not in PASSABLE_ENTITIES:
            blocked = True

        if building is not None and building not in PASSABLE_ENTITIES:
            blocked = True
        if building == EntityType.CORE and tile_data.get("building_team") != my_team:
            blocked = True

        if blocked:
            known_obstacles.add(neighbor_key)
        else:
            known_obstacles.discard(neighbor_key)


def calculate_micro_plan(
    bot,
    ct: Controller,
    start: Position,
    target: Position,
    known_obstacles: set[tuple[int, int]],
    temporary_obstacles: set[tuple[int, int]] | None = None,
    cardinal_only: bool = False,
    exact_only: bool = False,
) -> list:
    """
    `jon-5o` departure from `jon-5`: bounded 3-step search used when a full A*
    would be overkill or too expensive. This does not change macro policy; it
    only replaces some replans with a tiny local search.
    """
    utils.bump_profile(bot, "nav_micro_plan_calls")
    plan_start = time.time_ns() if utils.DEBUG_TURN_PROFILE else 0
    sx, sy = start.x, start.y
    tx, ty = target.x, target.y
    target_key = (tx, ty)
    temp_obstacles = temporary_obstacles or _EMPTY_BLOCKERS
    move_deltas = _CARDINAL_DELTAS if cardinal_only else _DIAGONAL_DELTAS
    tiling_back = bot.builder_mode == BuilderMode.TILING_BACK
    passable_buildings = PASSABLE_BUILDINGS
    bot_grid = bot.grid
    my_team = ct.get_team()
    connected_conveyors = getattr(bot, "connected_friendly_conveyors", {})
    map_w = ct.get_map_width()
    map_h = ct.get_map_height()

    start_raw_h = _heuristic(sx, sy, tx, ty, cardinal_only)
    best_path: list = []
    best_signature = (
        start_raw_h,
        _line_deviation_score(sx, sy, sx, sy, tx, ty),
        0.0,
        0,
    )
    best_seen: dict[tuple[int, int], tuple[float, int]] = {(sx, sy): (0.0, 0)}
    frontier = deque([(sx, sy, 0.0, 0, [])])
    expansions = 0
    frontier_peak = 1

    while frontier:
        frontier_peak = max(frontier_peak, len(frontier))
        cx, cy, current_g, depth, path = frontier.popleft()
        expansions += 1
        if depth >= MICRO_PLAN_STEP_LIMIT:
            continue

        for (ddx, ddy), direction, cost in move_deltas:
            nx, ny = cx + ddx, cy + ddy
            if not (0 <= nx < map_w and 0 <= ny < map_h):
                continue

            nb_key = (nx, ny)
            walkable, nb_data = _is_walkable_step(
                bot_grid,
                nb_key,
                target_key,
                known_obstacles,
                temp_obstacles,
                passable_buildings,
            )
            if not walkable:
                continue

            is_target = nb_key == target_key
            connected_load = connected_conveyors.get(nb_key, 0)
            new_g = current_g + _step_cost(
                nb_data,
                cost,
                tiling_back,
                direction,
                my_team,
                is_target,
                connected_load,
            )
            new_depth = depth + 1
            new_path = path + [(ActionType.CONVEYOR, direction)]
            raw_h = _heuristic(nx, ny, tx, ty, cardinal_only)
            deviation = _line_deviation_score(nx, ny, sx, sy, tx, ty)

            if is_target:
                utils.bump_profile(bot, "nav_micro_plan_expansions", expansions)
                utils.max_profile(bot, "nav_micro_plan_frontier_peak", frontier_peak)
                utils.max_profile(bot, "nav_micro_plan_path_len_peak", len(new_path))
                if plan_start:
                    utils.bump_profile(bot, "nav_micro_plan_ns", time.time_ns() - plan_start)
                return new_path

            if not exact_only and raw_h < start_raw_h:
                candidate_signature = (raw_h, deviation, new_g, new_depth)
                if candidate_signature < best_signature:
                    best_signature = candidate_signature
                    best_path = new_path

            seen_signature = best_seen.get(nb_key)
            if seen_signature is not None and seen_signature <= (new_g, new_depth):
                continue

            best_seen[nb_key] = (new_g, new_depth)
            frontier.append((nx, ny, new_g, new_depth, new_path))

    utils.bump_profile(bot, "nav_micro_plan_expansions", expansions)
    utils.max_profile(bot, "nav_micro_plan_frontier_peak", frontier_peak)
    utils.max_profile(bot, "nav_micro_plan_path_len_peak", len(best_path))
    if plan_start:
        utils.bump_profile(bot, "nav_micro_plan_ns", time.time_ns() - plan_start)
    return best_path


def _get_greedy_fallback_action(
    bot,
    ct: Controller,
    current_pos: Position,
    target_pos: Position,
    known_obstacles: set[tuple[int, int]],
    temporary_obstacles: set[tuple[int, int]],
    cardinal_only: bool,
):
    """
    Greedy fallback. Just move blindly towards the target, only ignoring obstacles
    """
    deltas = _CARDINAL_DELTAS if cardinal_only else _DIAGONAL_DELTAS
    target_key = (target_pos.x, target_pos.y)
    map_w = ct.get_map_width()
    map_h = ct.get_map_height()
    passable_buildings = PASSABLE_BUILDINGS
    best = None
    best_score = float("inf")

    for (ddx, ddy), direction, _ in deltas:
        nx, ny = current_pos.x + ddx, current_pos.y + ddy
        if not (0 <= nx < map_w and 0 <= ny < map_h):
            continue
        key = (nx, ny)
        if key in known_obstacles or key in temporary_obstacles:
            continue

        walkable, _ = _is_walkable_step(
            bot.grid,
            key,
            target_key,
            known_obstacles,
            temporary_obstacles,
            passable_buildings,
        )
        if not walkable:
            continue

        score = _heuristic(nx, ny, target_pos.x, target_pos.y, cardinal_only)
        if score < best_score:
            best = (ActionType.CONVEYOR, direction)
            best_score = score

    return best


def calculate_astar_path(
    bot,
    ct: Controller,
    start: Position,
    target: Position,
    known_obstacles: set[tuple[int, int]],
    temporary_obstacles: set[tuple[int, int]] | None = None,
    cardinal_only: bool = False,
    allow_bridges: bool | None = None,
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
    if allow_bridges is None:
        allow_bridges = (
            bot.builder_mode == BuilderMode.TILING_BACK
            and getattr(bot, "pending_bridge_plan", None) is None
        )

    start_time = time.time_ns()
    _bump_stat(bot, "astar_calls")
    utils.bump_profile(bot, "nav_astar_calls")

    # Cache map bounds once — avoids two method calls per neighbor.
    map_w = ct.get_map_width()
    map_h = ct.get_map_height()

    sx, sy = start.x, start.y
    tx, ty = target.x, target.y
    target_key = (tx, ty)
    max_iterations, _ = _get_astar_limits(bot)
    max_time_ns = get_available_astar_time_budget(bot, record_skip=True)
    if max_time_ns <= 0:
        utils.bump_profile(bot, "nav_astar_budget_zero")
        utils.bump_profile(bot, "nav_astar_ns", time.time_ns() - start_time)
        return []

    # Merge obstacle sets once upfront — one set lookup per neighbor instead of two.
    merged_obstacles = known_obstacles
    if temporary_obstacles:
        merged_obstacles = known_obstacles | temporary_obstacles
    merged_obstacles_discard_target = target_key in merged_obstacles

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
    bot_grid_get = bot_grid.get  # local ref for hot-path dict lookup
    my_team = ct.get_team()
    connected_conveyors = getattr(bot, "connected_friendly_conveyors", {})
    _impassable = IMPASSABLE_TILES
    _passable = PASSABLE_BUILDINGS
    _transport = TRANSPORT_BUILDINGS

    # Precompute line-deviation anchor deltas.
    ldx_anchor = tx - sx
    ldy_anchor = sy - ty  # note: intentional sign for cross-product

    # Heap entries: (f_cost, raw_h, line_deviation, g_cost, counter, x, y)
    counter = 0
    open_set: list = []
    start_dx = abs(sx - tx)
    start_dy = abs(sy - ty)
    start_raw_h = (start_dx + start_dy) if cardinal_only else max(start_dx, start_dy)
    heapq.heappush(
        open_set,
        (
            start_raw_h * h_mult,
            start_raw_h,
            abs(ldx_anchor * (sy - sy) - (sx - sx) * ldy_anchor),
            0.0,
            counter,
            sx,
            sy,
        ),
    )

    iterations = 0
    found = False
    timeout_hit = False
    iteration_hit = False
    open_set_peak = 1
    closed: set[tuple[int, int]] = set()
    _time_ns = time.time_ns
    _heappush = heapq.heappush
    _heappop = heapq.heappop
    _CONVEYOR_ACTION = ActionType.CONVEYOR
    _BRIDGE_ACTION = ActionType.BRIDGE
    _snap = SNAP_LINE_MULTIPLIER
    _wrong_dir_penalty = WRONG_DIRECTION_CONVEYOR_PENALTY

    while open_set:
        open_set_peak = max(open_set_peak, len(open_set))
        if (_time_ns() - start_time) >= max_time_ns:
            timeout_hit = True
            break
        if iterations >= max_iterations:
            iteration_hit = True
            break

        _, _, _, popped_g, _, cx, cy = _heappop(open_set)
        current_key = (cx, cy)
        if current_key in closed:
            continue
        closed.add(current_key)

        if current_key == target_key:
            found = True
            break

        iterations += 1
        current_g = g_costs[current_key]

        # ── 1. Cardinal / diagonal conveyor moves ───────────────────────────
        for (ddx, ddy), direction, base_cost in move_deltas:
            nx, ny = cx + ddx, cy + ddy

            if not (0 <= nx < map_w and 0 <= ny < map_h):
                continue

            nb_key = (nx, ny)

            # Skip already-expanded nodes (closed set pruning).
            if nb_key in closed:
                continue

            # Inlined _is_walkable_step — avoid function call overhead.
            is_target = nb_key == target_key
            if nb_key in merged_obstacles and not (is_target and merged_obstacles_discard_target):
                continue

            nb_data = bot_grid_get(nb_key)
            if nb_data is not None:
                nb_env = nb_data.get("env")
                if nb_env in _impassable:
                    continue
                b_type = nb_data.get("building")
                if b_type is not None and b_type not in _passable and not is_target:
                    continue
            else:
                b_type = None

            # Inlined _step_cost — fast-path common cases.
            if b_type is None:
                step = base_cost
            elif tiling_back and b_type in _transport:
                if nb_data.get("building_team") == my_team:
                    if (
                        is_target
                        or b_type == EntityType.BRIDGE
                        or nb_data.get("building_dir") == direction
                    ):
                        step = base_cost * _snap
                    else:
                        step = base_cost + _wrong_dir_penalty
                else:
                    step = base_cost
            elif b_type in _passable:
                step = base_cost
            else:
                step = base_cost + ROAD_BUILD_PENALTY

            if tiling_back and is_target:
                step += connected_conveyor_load_penalty(
                    connected_conveyors.get(nb_key, 0)
                )

            new_g = current_g + step

            if nb_key not in g_costs or new_g < g_costs[nb_key]:
                g_costs[nb_key] = new_g
                came_from[nb_key] = (cx, cy, (_CONVEYOR_ACTION, direction))
                # Inlined heuristic — compute raw_h once, derive f.
                dx = abs(nx - tx)
                dy = abs(ny - ty)
                raw_h = (dx + dy) if cardinal_only else max(dx, dy)
                f = new_g + raw_h * h_mult
                # Inlined _line_deviation_score.
                line_dev = abs(ldx_anchor * (sy - ny) - (sx - nx) * ldy_anchor)
                counter += 1
                _heappush(
                    open_set,
                    (f, raw_h, line_dev, new_g, counter, nx, ny),
                )

        # 2. Bridge moves (tiling back only)
        if allow_bridges and tiling_back:
            # --- PRUNING: Prevent State Explosion ---
            needs_bridge = False

            current_data = bot_grid_get(current_key)
            if current_data and current_data.get("building") not in {
                None,
                EntityType.ROAD,
                EntityType.MARKER,
            }:
                needs_bridge = True

            if not needs_bridge:
                for (ddx, ddy), _, _ in _CARDINAL_DELTAS:
                    check_key = (cx + ddx, cy + ddy)

                    if check_key in known_obstacles:
                        needs_bridge = True
                        break

                    check_data = bot_grid_get(check_key)
                    if check_data is not None:
                        cb_type = check_data.get("building")
                        if cb_type not in {None, EntityType.ROAD, EntityType.MARKER}:
                            needs_bridge = True
                            break

            if needs_bridge:
                c_dx = abs(cx - tx)
                c_dy = abs(cy - ty)
                current_raw_h = (c_dx + c_dy) if cardinal_only else max(c_dx, c_dy)
                for (ddx, ddy), cost in BRIDGE_OFFSETS:
                    nx, ny = cx + ddx, cy + ddy

                    if not (0 <= nx < map_w and 0 <= ny < map_h):
                        continue

                    nb_key = (nx, ny)
                    is_connected_line = nb_key in connected_conveyors
                    b_dx = abs(nx - tx)
                    b_dy = abs(ny - ty)
                    raw_h = (b_dx + b_dy) if cardinal_only else max(b_dx, b_dy)
                    progress_dot = (tx - cx) * ddx + (ty - cy) * ddy
                    if (
                        nb_key != target_key
                        and not is_connected_line
                        and (progress_dot <= 0 or raw_h >= current_raw_h)
                    ):
                        continue

                    # Inlined walkability check for bridge targets.
                    if nb_key in merged_obstacles and not (nb_key == target_key and merged_obstacles_discard_target):
                        continue
                    nb_data = bot_grid_get(nb_key)
                    if nb_data is not None:
                        if nb_data.get("env") in _impassable:
                            continue
                        bb_type = nb_data.get("building")
                        if bb_type is not None and bb_type not in _passable and nb_key != target_key:
                            continue

                    new_g = current_g + cost
                    if nb_key not in g_costs or new_g < g_costs[nb_key]:
                        g_costs[nb_key] = new_g
                        bridge_target = Position(nx, ny)
                        came_from[nb_key] = (cx, cy, (_BRIDGE_ACTION, bridge_target))
                        f = new_g + raw_h * h_mult
                        line_dev = abs(ldx_anchor * (sy - ny) - (sx - nx) * ldy_anchor)
                        counter += 1
                        _heappush(
                            open_set,
                            (f, raw_h, line_dev, new_g, counter, nx, ny),
                        )

    goal_key = target_key

    if not found:
        if DEBUG_PATH_LOGGING:
            ct.draw_indicator_dot(start, 255, 165, 0)
        msg = f"A* failed after {iterations} iterations"
        if timeout_hit:
            _bump_stat(bot, "astar_timeout_exits")
        if iteration_hit:
            _bump_stat(bot, "astar_iteration_exits")
        if throws_exception_on_failure:
            raise Exception(msg)
        bot.logger.print(msg)

        if not open_set:
            utils.bump_profile(bot, "nav_astar_iterations", iterations)
            utils.max_profile(bot, "nav_astar_open_peak", open_set_peak)
            utils.bump_profile(bot, "nav_astar_ns", time.time_ns() - start_time)
            return []

        # Best-effort: back-track from the open-set node with the lowest f-cost.
        # It's the node closest to the goal we managed to reach.
        _, _, _, _, _, bx, by = open_set[0]  # heapq[0] is always the smallest
        goal_key = (bx, by)
        _bump_stat(bot, "astar_best_effort")

    # Walk the came_from chain and reverse.
    path: list = []
    key = goal_key
    while came_from.get(key) is not None:
        px, py, action = came_from[key]
        path.append(action)
        key = (px, py)
    path.reverse()
    _bump_stat(bot, "astar_nodes_expanded", iterations)
    stats = getattr(bot, "stats", None)
    if stats is not None:
        stats["astar_open_set_peak"] = max(
            stats.get("astar_open_set_peak", 0), open_set_peak
        )
    utils.bump_profile(bot, "nav_astar_iterations", iterations)
    if timeout_hit:
        utils.bump_profile(bot, "nav_astar_timeout_turns")
    if iteration_hit:
        utils.bump_profile(bot, "nav_astar_iteration_limit_turns")
    if not found:
        utils.bump_profile(bot, "nav_astar_best_effort_turns")
    utils.max_profile(bot, "nav_astar_open_peak", open_set_peak)
    utils.max_profile(bot, "nav_astar_path_len_peak", len(path))
    utils.bump_profile(bot, "nav_astar_ns", time.time_ns() - start_time)
    return path


def _obstacle_fingerprint(obstacles: set[tuple[int, int]]) -> tuple[int, int]:
    if not obstacles:
        return (0, 0)
    return (len(obstacles), hash(frozenset(obstacles)))


def _planner_signature(
    start: Position,
    target: Position,
    known_obstacles: set[tuple[int, int]],
    temporary_obstacles: set[tuple[int, int]],
    *,
    cardinal_only: bool,
    tiling_back: bool,
    allow_bridges: bool,
) -> tuple:
    known_fingerprint = _obstacle_fingerprint(known_obstacles)
    temp_fingerprint = _obstacle_fingerprint(temporary_obstacles)
    return (
        start.x,
        start.y,
        target.x,
        target.y,
        cardinal_only,
        tiling_back,
        allow_bridges,
        known_fingerprint,
        temp_fingerprint,
    )


def _reconstruct_parent_path(
    came_from: dict[tuple[int, int], tuple | None],
    goal_key: tuple[int, int],
) -> list:
    path: list = []
    key = goal_key
    while came_from.get(key) is not None:
        px, py, action = came_from[key]
        path.append(action)
        key = (px, py)
    path.reverse()
    return path


def _resume_anytime_astar(
    bot,
    ct: Controller,
    start: Position,
    target: Position,
    known_obstacles: set[tuple[int, int]],
    *,
    temporary_obstacles: set[tuple[int, int]] | None = None,
    cardinal_only: bool = False,
    planner_state: dict | None = None,
) -> tuple[list, bool, dict | None]:
    start_time = time.time_ns()
    map_w = ct.get_map_width()
    map_h = ct.get_map_height()
    sx, sy = start.x, start.y
    tx, ty = target.x, target.y
    target_key = (tx, ty)
    temp_obstacles = temporary_obstacles or _EMPTY_BLOCKERS
    tiling_back = bot.builder_mode == BuilderMode.TILING_BACK
    allow_bridges = tiling_back and getattr(bot, "pending_bridge_plan", None) is None
    signature = _planner_signature(
        start,
        target,
        known_obstacles,
        temp_obstacles,
        cardinal_only=cardinal_only,
        tiling_back=tiling_back,
        allow_bridges=allow_bridges,
    )

    if planner_state is None or planner_state.get("signature") != signature:
        start_dx = abs(sx - tx)
        start_dy = abs(sy - ty)
        start_raw_h = (start_dx + start_dy) if cardinal_only else max(start_dx, start_dy)
        planner_state = {
            "signature": signature,
            "open_set": [
                (
                    start_raw_h * (1.0 if tiling_back else (1.0 + ROAD_BUILD_PENALTY)),
                    start_raw_h,
                    0,
                    0.0,
                    0,
                    sx,
                    sy,
                )
            ],
            "came_from": {(sx, sy): None},
            "g_costs": {(sx, sy): 0.0},
            "depths": {(sx, sy): 0},
            "closed": set(),
            "counter": 0,
            "iterations": 0,
            "best_key": (sx, sy),
            "best_signature": (start_raw_h, 0, 0.0, 0),
            "timeout_hit": False,
            "iteration_hit": False,
        }

    max_iterations, mode_budget_ns = _get_astar_limits(bot)
    slice_iterations = max(ANYTIME_ASTAR_MIN_ITERATIONS, max_iterations // ANYTIME_ASTAR_ITERATION_DIVISOR)
    available_budget_ns = get_available_astar_time_budget(bot, record_skip=True)
    if available_budget_ns <= 0:
        utils.bump_profile(bot, "nav_anytime_budget_zero")
        return [], False, planner_state
    max_time_ns = min(mode_budget_ns, available_budget_ns)
    h_mult = 1.0 if tiling_back else (1.0 + ROAD_BUILD_PENALTY)
    bot_grid = bot.grid
    bot_grid_get = bot_grid.get
    my_team = ct.get_team()
    connected_conveyors = getattr(bot, "connected_friendly_conveyors", {})
    move_deltas = _CARDINAL_DELTAS if cardinal_only else _DIAGONAL_DELTAS
    _impassable = IMPASSABLE_TILES
    _passable = PASSABLE_BUILDINGS
    _transport = TRANSPORT_BUILDINGS
    _snap = SNAP_LINE_MULTIPLIER
    _wrong_dir_penalty = WRONG_DIRECTION_CONVEYOR_PENALTY

    # Merge obstacle sets once.
    merged_obstacles = known_obstacles
    if temp_obstacles:
        merged_obstacles = known_obstacles | temp_obstacles
    merged_obstacles_discard_target = target_key in merged_obstacles

    # Precompute line-deviation anchor deltas.
    ldx_anchor = tx - sx
    ldy_anchor = sy - ty

    open_set = planner_state["open_set"]
    came_from = planner_state["came_from"]
    g_costs = planner_state["g_costs"]
    depths = planner_state.setdefault("depths", {(sx, sy): 0})
    closed: set = planner_state.setdefault("closed", set())
    counter = planner_state.get("counter", 0)
    best_key = planner_state.get("best_key", (sx, sy))
    best_signature = planner_state.get("best_signature", (float("inf"), float("inf"), float("inf"), float("inf")))
    iterations = 0
    _time_ns = time.time_ns
    _heappush = heapq.heappush
    _heappop = heapq.heappop
    _CONVEYOR_ACTION = ActionType.CONVEYOR
    _BRIDGE_ACTION = ActionType.BRIDGE

    utils.bump_profile(bot, "nav_anytime_calls")

    while open_set:
        if iterations >= slice_iterations:
            planner_state["iteration_hit"] = True
            break
        if _time_ns() - start_time >= max_time_ns:
            planner_state["timeout_hit"] = True
            break

        iterations += 1
        _, _, _, popped_g, _, cx, cy = _heappop(open_set)
        current_key = (cx, cy)
        if current_key in closed:
            continue
        closed.add(current_key)
        current_g = g_costs[current_key]
        if current_key == target_key:
            planner_state["open_set"] = open_set
            planner_state["counter"] = counter
            planner_state["iterations"] = planner_state.get("iterations", 0) + iterations
            path = _reconstruct_parent_path(came_from, target_key)
            utils.bump_profile(bot, "nav_anytime_exact_turns")
            utils.bump_profile(bot, "nav_anytime_iterations", iterations)
            utils.bump_profile(bot, "nav_anytime_ns", _time_ns() - start_time)
            return path, True, None

        current_depth = depths[current_key]
        for (ddx, ddy), direction, base_cost in move_deltas:
            nx, ny = cx + ddx, cy + ddy
            if not (0 <= nx < map_w and 0 <= ny < map_h):
                continue
            nb_key = (nx, ny)
            if nb_key in closed:
                continue
            # Inlined walkability check.
            is_target = nb_key == target_key
            if nb_key in merged_obstacles and not (is_target and merged_obstacles_discard_target):
                continue
            nb_data = bot_grid_get(nb_key)
            if nb_data is not None:
                if nb_data.get("env") in _impassable:
                    continue
                b_type = nb_data.get("building")
                if b_type is not None and b_type not in _passable and not is_target:
                    continue
            else:
                b_type = None
            # Inlined step cost.
            if b_type is None:
                step = base_cost
            elif tiling_back and b_type in _transport:
                if nb_data.get("building_team") == my_team:
                    if (
                        is_target
                        or b_type == EntityType.BRIDGE
                        or nb_data.get("building_dir") == direction
                    ):
                        step = base_cost * _snap
                    else:
                        step = base_cost + _wrong_dir_penalty
                else:
                    step = base_cost
            elif b_type in _passable:
                step = base_cost
            else:
                step = base_cost + ROAD_BUILD_PENALTY
            if tiling_back and is_target:
                step += connected_conveyor_load_penalty(
                    connected_conveyors.get(nb_key, 0)
                )
            new_g = current_g + step
            new_depth = current_depth + 1
            if nb_key not in g_costs or new_g < g_costs[nb_key]:
                g_costs[nb_key] = new_g
                depths[nb_key] = new_depth
                came_from[nb_key] = (cx, cy, (_CONVEYOR_ACTION, direction))
                dx = abs(nx - tx)
                dy = abs(ny - ty)
                raw_h = (dx + dy) if cardinal_only else max(dx, dy)
                line_dev = abs(ldx_anchor * (sy - ny) - (sx - nx) * ldy_anchor)
                candidate_signature = (raw_h, line_dev, new_g, new_depth)
                if candidate_signature < best_signature:
                    best_signature = candidate_signature
                    best_key = nb_key
                counter += 1
                _heappush(
                    open_set,
                    (new_g + raw_h * h_mult, raw_h, line_dev, new_g, counter, nx, ny),
                )

        if allow_bridges and tiling_back:
            c_dx = abs(cx - tx)
            c_dy = abs(cy - ty)
            current_raw_h = (c_dx + c_dy) if cardinal_only else max(c_dx, c_dy)
            for (ddx, ddy), cost in BRIDGE_OFFSETS:
                nx, ny = cx + ddx, cy + ddy
                if not (0 <= nx < map_w and 0 <= ny < map_h):
                    continue
                nb_key = (nx, ny)
                b_dx = abs(nx - tx)
                b_dy = abs(ny - ty)
                raw_h = (b_dx + b_dy) if cardinal_only else max(b_dx, b_dy)
                progress_dot = (tx - cx) * ddx + (ty - cy) * ddy
                if nb_key != target_key and (progress_dot <= 0 or raw_h >= current_raw_h):
                    continue
                # Inlined walkability check.
                if nb_key in merged_obstacles and not (nb_key == target_key and merged_obstacles_discard_target):
                    continue
                nb_data = bot_grid_get(nb_key)
                if nb_data is not None:
                    if nb_data.get("env") in _impassable:
                        continue
                    bb_type = nb_data.get("building")
                    if bb_type is not None and bb_type not in _passable and nb_key != target_key:
                        continue
                new_g = current_g + cost
                if nb_key not in g_costs or new_g < g_costs[nb_key]:
                    new_depth = current_depth + 1
                    g_costs[nb_key] = new_g
                    depths[nb_key] = new_depth
                    bridge_target = Position(nx, ny)
                    came_from[nb_key] = (cx, cy, (_BRIDGE_ACTION, bridge_target))
                    line_dev = abs(ldx_anchor * (sy - ny) - (sx - nx) * ldy_anchor)
                    candidate_signature = (raw_h, line_dev, new_g, new_depth)
                    if candidate_signature < best_signature:
                        best_signature = candidate_signature
                        best_key = nb_key
                    counter += 1
                    _heappush(
                        open_set,
                        (
                            new_g + _heuristic(nx, ny, tx, ty, cardinal_only, h_mult),
                            raw_h,
                            _line_deviation_score(nx, ny, sx, sy, tx, ty),
                            new_g,
                            counter,
                            nx,
                            ny,
                        ),
                    )

    planner_state["open_set"] = open_set
    planner_state["came_from"] = came_from
    planner_state["g_costs"] = g_costs
    planner_state["depths"] = depths
    planner_state["counter"] = counter
    planner_state["best_key"] = best_key
    planner_state["best_signature"] = best_signature
    planner_state["iterations"] = planner_state.get("iterations", 0) + iterations
    utils.bump_profile(bot, "nav_anytime_iterations", iterations)
    utils.bump_profile(bot, "nav_anytime_ns", time.time_ns() - start_time)

    if not open_set:
        if best_key == (sx, sy):
            return [], False, None
        return _reconstruct_parent_path(came_from, best_key), False, None

    if best_key == (sx, sy):
        return [], False, planner_state
    return _reconstruct_parent_path(came_from, best_key), False, planner_state


def _simulate_path_endpoint(current_pos: Position, path: list) -> Position:
    simulated_pos = current_pos
    for action_type, action_val in path:
        simulated_pos = (
            simulated_pos.add(action_val)
            if action_type == ActionType.CONVEYOR
            else action_val
        )
    return simulated_pos


def compute_pathfinding_step(
    bot,
    ct: Controller,
    current_pos: Position,
    target_pos: Position,
    current_state: dict,
    cardinal_only: bool = False,
    throws_exception_on_failure: bool = False,
) -> tuple:
    # This wrapper is where path reuse happens. It keeps A* bounded by only
    # replanning when the target changes, the near-term path is blocked, or the
    # cached route has been fully consumed.
    utils.bump_profile(bot, "nav_compute_calls")
    compute_start = time.time_ns() if utils.DEBUG_TURN_PROFILE else 0

    def finish(move_action, state):
        if compute_start:
            utils.bump_profile(bot, "nav_compute_ns", time.time_ns() - compute_start)
        return move_action, state

    state = current_state.copy()
    state["path"] = list(state["path"])

    # 1. Expire temporary obstacles
    active_temp_obs = {
        pos: expiry
        for pos, expiry in state.get("temporary_obstacles", {}).items()
        if expiry > ct.get_current_round()
    }
    state["temporary_obstacles"] = active_temp_obs
    utils.max_profile(bot, "nav_active_temp_obstacles_peak", len(active_temp_obs))
    utils.max_profile(bot, "nav_cached_path_len_peak", len(state["path"]))

    # # 2. Update obstacle memory from immediate neighbours
    _refresh_local_obstacle_memory(
        bot, current_pos, state["known_obstacles"], ct.get_team()
    )

    # 3. Invalidate cached path if target changed
    target_tuple = (target_pos.x, target_pos.y)
    if state.get("current_target") != target_tuple:
        _bump_stat(bot, "path_invalid_target")
        state["path"] = []
        state["current_target"] = target_tuple
        state["planner_state"] = None

    if current_pos == target_pos:
        state["path"] = []
        utils.bump_profile(bot, "nav_already_at_target")
        state["planner_state"] = None
        return finish(None, state)

    # 4. Validate the next few steps against current obstacles
    if state["path"]:
        simulated_pos = current_pos
        blocked_index = None
        blocked_key = None
        for idx, (next_type, next_val) in enumerate(
            state["path"][:A_STAR_LOOKAHEAD_CANCEL]
        ):
            utils.bump_profile(bot, "nav_lookahead_checks")
            simulated_pos = (
                simulated_pos.add(next_val)
                if next_type == ActionType.CONVEYOR
                else next_val
            )
            pos_key = (simulated_pos.x, simulated_pos.y)
            if pos_key in state["known_obstacles"] or pos_key in active_temp_obs:
                if pos_key != target_tuple:
                    blocked_index = idx
                    blocked_key = pos_key
                    break

        if blocked_index is not None:
            if blocked_key in active_temp_obs:
                _bump_stat(bot, "path_invalid_temp")
            else:
                _bump_stat(bot, "path_invalid_known")

            if blocked_index == 0:
                state["path"] = []
            else:
                state["path"] = state["path"][:blocked_index]
                _bump_stat(bot, "path_trimmed")

    # 5. Recompute if empty
    # 5a. Force recompute if a short sub-path doesn't end at the target (economy
    # modes only; assault bots commit to short paths intentionally).
    if state["path"] and len(state["path"]) < 3 and bot.builder_mode != BuilderMode.ASSAULTING:
        simulated_pos = current_pos
        for next_type, next_val in state["path"]:
            simulated_pos = (
                simulated_pos.add(next_val)
                if next_type == ActionType.CONVEYOR
                else next_val
            )
        if simulated_pos != target_pos:
            state["path"] = []
    if not state["path"]:
        obstacle_signature = (
            len(state["known_obstacles"]),
            len(active_temp_obs),
            target_tuple,
        )
        round_now = ct.get_current_round()
        temp_blockers = set(active_temp_obs.keys())
        temp_blockers.discard(target_tuple)
        known_obs = state["known_obstacles"]
        target_near = (
            _heuristic(
                current_pos.x,
                current_pos.y,
                target_pos.x,
                target_pos.y,
                cardinal_only,
            )
            <= MICRO_PLAN_TRIGGER_DISTANCE
        )
        repeated_same_turn = (
            state.get("last_replan_signature") == obstacle_signature
            and state.get("last_replan_round") == round_now
        )
        budget_too_low = get_available_astar_time_budget(bot) <= 0
        utils.bump_profile(bot, "nav_replan_turns")

        if target_near or repeated_same_turn or budget_too_low:
            if target_near:
                utils.bump_profile(bot, "nav_target_near_replans")
            if repeated_same_turn:
                utils.bump_profile(bot, "nav_repeated_same_turn_replans")
            if budget_too_low:
                utils.bump_profile(bot, "nav_budget_too_low_replans")
            state["path"] = calculate_micro_plan(
                bot,
                ct,
                current_pos,
                target_pos,
                known_obs,
                temporary_obstacles=temp_blockers,
                cardinal_only=cardinal_only,
            )
            if state["path"]:
                _bump_stat(bot, "micro_plan_used")
                utils.max_profile(bot, "nav_path_len_peak", len(state["path"]))

        if repeated_same_turn and not state["path"]:
            anytime_path, anytime_exact, planner_state = _resume_anytime_astar(
                bot,
                ct,
                current_pos,
                target_pos,
                known_obs,
                temporary_obstacles=temp_blockers,
                cardinal_only=cardinal_only,
                planner_state=state.get("planner_state"),
            )
            state["planner_state"] = planner_state
            if anytime_path:
                state["path"] = anytime_path
                if anytime_exact:
                    _bump_stat(bot, "anytime_exact_paths")
                    utils.bump_profile(bot, "nav_anytime_exact_paths")
                else:
                    _bump_stat(bot, "anytime_partial_paths")
                    utils.bump_profile(bot, "nav_anytime_partial_paths")
                return finish(state["path"][0], state)
            return finish(None, state)

        if budget_too_low and not state["path"]:
            anytime_path, anytime_exact, planner_state = _resume_anytime_astar(
                bot,
                ct,
                current_pos,
                target_pos,
                known_obs,
                temporary_obstacles=temp_blockers,
                cardinal_only=cardinal_only,
                planner_state=state.get("planner_state"),
            )
            state["planner_state"] = planner_state
            if anytime_path:
                state["path"] = anytime_path
                if anytime_exact:
                    _bump_stat(bot, "anytime_exact_paths")
                    utils.bump_profile(bot, "nav_anytime_exact_paths")
                else:
                    _bump_stat(bot, "anytime_partial_paths")
                    utils.bump_profile(bot, "nav_anytime_partial_paths")
                return finish(state["path"][0], state)
            return finish(None, state)

        if not state["path"]:
            anytime_first = state.get("planner_state") is not None
            if anytime_first:
                anytime_path, anytime_exact, planner_state = _resume_anytime_astar(
                    bot,
                    ct,
                    current_pos,
                    target_pos,
                    known_obs,
                    temporary_obstacles=temp_blockers,
                    cardinal_only=cardinal_only,
                    planner_state=state.get("planner_state"),
                )
                state["planner_state"] = planner_state
                if anytime_path:
                    state["path"] = anytime_path
                    if anytime_exact:
                        _bump_stat(bot, "anytime_exact_paths")
                        utils.bump_profile(bot, "nav_anytime_exact_paths")
                    else:
                        _bump_stat(bot, "anytime_partial_paths")
                        utils.bump_profile(bot, "nav_anytime_partial_paths")
            if not state["path"]:
                _bump_stat(bot, "astar_recomputes")
                state["path"] = calculate_astar_path(
                    bot,
                    ct,
                    current_pos,
                    target_pos,
                    known_obs,
                    temporary_obstacles=temp_blockers,
                    cardinal_only=cardinal_only,
                    throws_exception_on_failure=throws_exception_on_failure,
                )
                if state["path"]:
                    state["planner_state"] = None
                elif not budget_too_low:
                    anytime_path, anytime_exact, planner_state = _resume_anytime_astar(
                        bot,
                        ct,
                        current_pos,
                        target_pos,
                        known_obs,
                        temporary_obstacles=temp_blockers,
                        cardinal_only=cardinal_only,
                        planner_state=state.get("planner_state"),
                    )
                    state["planner_state"] = planner_state
                    if anytime_path:
                        state["path"] = anytime_path
                        if anytime_exact:
                            _bump_stat(bot, "anytime_exact_paths")
                            utils.bump_profile(bot, "nav_anytime_exact_paths")
                        else:
                            _bump_stat(bot, "anytime_partial_paths")
                            utils.bump_profile(bot, "nav_anytime_partial_paths")
            if state["path"]:
                state["last_replan_signature"] = obstacle_signature
                state["last_replan_round"] = round_now
                utils.max_profile(bot, "nav_path_len_peak", len(state["path"]))

        if not state["path"]:
            return finish(None, state)
    else:
        _bump_stat(bot, "astar_cache_hits")
        utils.bump_profile(bot, "nav_path_cache_hit_turns")

    # 6. Get the next step; optionally consume it
    log_path(bot, ct, state["path"])
    move_action = state["path"][0] if state["path"] else None

    return finish(move_action, state)


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


def _reset_shared_progress_state(
    progress_state: dict,
    *,
    mode_name: str | None,
    target_key: tuple[int, int] | None,
    last_key: tuple[int, int],
) -> None:
    progress_state["mode_name"] = mode_name
    progress_state["target_key"] = target_key
    progress_state["last_key"] = last_key
    progress_state["prior_key"] = None
    progress_state["stalled_turns"] = 0


def _reset_pathfinding_recovery_state(state: dict) -> None:
    state["path"] = []
    state["planner_state"] = None
    state["last_replan_signature"] = None
    state["last_replan_round"] = -1


def note_shared_builder_progress(
    bot,
    ct: Controller,
    target_pos: Position,
    *,
    start_pos: Position,
    final_pos: Position,
    moved: bool,
    attempted_next_pos: Position | None = None,
) -> bool:
    del start_pos
    if getattr(bot, "builder_mode", None) not in SHARED_PROGRESS_MODES:
        return False

    progress_state = bot.pathfinding_state.setdefault("progress_state", {})
    bot.pathfinding_state["shared_progress_stalled"] = False
    mode_name = getattr(getattr(bot, "builder_mode", None), "name", None)
    target_key = None if target_pos is None else (target_pos.x, target_pos.y)
    final_key = (final_pos.x, final_pos.y)

    if (
        progress_state.get("mode_name") != mode_name
        or progress_state.get("target_key") != target_key
    ):
        _reset_shared_progress_state(
            progress_state,
            mode_name=mode_name,
            target_key=target_key,
            last_key=final_key,
        )
        return False

    if final_key == target_key:
        _reset_shared_progress_state(
            progress_state,
            mode_name=mode_name,
            target_key=target_key,
            last_key=final_key,
        )
        return False

    last_key = progress_state.get("last_key")
    prior_key = progress_state.get("prior_key")
    stationary = final_key == last_key
    ping_pong = prior_key is not None and final_key == prior_key and final_key != last_key

    if moved and not ping_pong:
        progress_state["stalled_turns"] = 0
    elif stationary or ping_pong or not moved:
        progress_state["stalled_turns"] = progress_state.get("stalled_turns", 0) + 1
    else:
        progress_state["stalled_turns"] = 0

    progress_state["prior_key"] = last_key
    progress_state["last_key"] = final_key

    if progress_state["stalled_turns"] < SHARED_PROGRESS_STALL_LIMIT:
        return False

    _reset_pathfinding_recovery_state(bot.pathfinding_state)

    block_key = None
    if ping_pong and last_key is not None and last_key != target_key:
        block_key = last_key
    elif attempted_next_pos is not None:
        attempted_key = (attempted_next_pos.x, attempted_next_pos.y)
        if attempted_key != target_key:
            block_key = attempted_key

    if block_key is not None:
        bot.pathfinding_state.setdefault("temporary_obstacles", {})[block_key] = (
            ct.get_current_round() + SHARED_PROGRESS_TTL
        )

    if getattr(bot, "builder_mode", None) == BuilderMode.TILING_BACK:
        bot.pending_build = None
        bot.pending_bridge_plan = None
        bot.bridge_transit_path = None
        bot.bridge_transit_cooldown_until = -1
        if hasattr(bot, "saved_post_bridge_path"):
            bot.saved_post_bridge_path = []

    bot.logger.log(
        f"shared recovery: reset stalled {mode_name} route toward {target_pos}"
    )
    bot.pathfinding_state["shared_progress_stalled"] = True
    _reset_shared_progress_state(
        progress_state,
        mode_name=mode_name,
        target_key=target_key,
        last_key=final_key,
    )
    return True


def consume_shared_progress_stall(bot) -> bool:
    return bool(bot.pathfinding_state.pop("shared_progress_stalled", False))


def try_pathfinding_move(
    bot,
    ct: Controller,
    target_pos: Position,
    cardinal_only: bool = False,
    throws_exception_on_failure: bool = False,
    allow_enemy_builder_at_target: bool = False,
) -> tuple[bool, Position]:
    """
    Executes one move step and updates memory.
    Returns (success, current_position).
    """
    utils.bump_profile(bot, "nav_try_move_calls")
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
    attempted_next_pos = None

    if move_action is None:
        if _try_opening_shell_escape(bot, ct, current_pos):
            utils.bump_profile(bot, "nav_opening_shell_escape_turns")
            final_pos = ct.get_position()
            note_shared_builder_progress(
                bot,
                ct,
                target_pos,
                start_pos=current_pos,
                final_pos=final_pos,
                moved=True,
            )
            return True, final_pos
        utils.bump_profile(bot, "nav_no_move_action_turns")
        note_shared_builder_progress(
            bot,
            ct,
            target_pos,
            start_pos=current_pos,
            final_pos=current_pos,
            moved=False,
        )
        return False, current_pos

    action_type, action_val = move_action

    # Resolve next_pos and move_dir regardless of action type, so neither is
    # ever unbound below (was a latent NameError in the original code).
    if action_type == ActionType.BRIDGE:
        next_pos = action_val
        move_dir = None
        utils.bump_profile(bot, "nav_bridge_actions")
    else:
        move_dir = action_val
        next_pos = current_pos.add(action_val)
        utils.bump_profile(bot, "nav_conveyor_actions")
    attempted_next_pos = next_pos

    if bot.builder_mode not in {BuilderMode.TILING_BACK, BuilderMode.ASSAULTING}:
        utils.destroy_marker_if_present(ct, next_pos)
        if ct.can_build_road(next_pos):
            ct.build_road(next_pos)

    # Execute move
    if move_dir is not None and ct.can_move(move_dir):
        ct.move(move_dir)
        if bot.pathfinding_state["path"]:
            bot.pathfinding_state["path"].pop(0)
        utils.bump_profile(bot, "nav_move_success_turns")
        final_pos = ct.get_position()
        note_shared_builder_progress(
            bot,
            ct,
            target_pos,
            start_pos=current_pos,
            final_pos=final_pos,
            moved=True,
            attempted_next_pos=attempted_next_pos,
        )
        return True, final_pos

    # Stumped: if blocked by a friendly builder, mark as temp obstacle
    # so the planner routes around the congestion next turn.
    next_key = (next_pos.x, next_pos.y)
    grid_entry = bot.grid.get(next_key, {})
    if (
        grid_entry.get("entity") == EntityType.BUILDER_BOT
        and grid_entry.get("entity_team") == ct.get_team()
    ):
        utils.bump_profile(bot, "nav_blocked_friendly_builder_turns")
        bot.pathfinding_state.setdefault("temporary_obstacles", {})[next_key] = (
            ct.get_current_round() + 8
        )
    elif (
        bot.builder_mode == BuilderMode.ASSAULTING
        and grid_entry.get("entity") == EntityType.BUILDER_BOT
        and grid_entry.get("entity_team") is not None
        and grid_entry.get("entity_team") != ct.get_team()
    ):
        utils.bump_profile(bot, "nav_blocked_enemy_builder_turns")
        target_key = (target_pos.x, target_pos.y)
        if not (allow_enemy_builder_at_target and next_key == target_key):
            bot.logger.log(f"Blocked by enemy builder bot at {next_pos}; replanning")
            bot.pathfinding_state.setdefault("temporary_obstacles", {})[next_key] = (
                ct.get_current_round() + 3
            )

    note_shared_builder_progress(
        bot,
        ct,
        target_pos,
        start_pos=current_pos,
        final_pos=current_pos,
        moved=False,
        attempted_next_pos=attempted_next_pos,
    )
    return False, current_pos


def _assault_reset_navigation(bot, target_pos: Position | None = None) -> dict:
    state = getattr(bot, "assault_nav_state", None)
    if state is None:
        state = {}
        bot.assault_nav_state = state

    state["current_target"] = None if target_pos is None else (target_pos.x, target_pos.y)
    state["bfs_path"] = []
    state["frontier_target"] = None
    return state


def _expire_temporary_obstacles(state: dict, current_round: int) -> None:
    state["temporary_obstacles"] = {
        pos: expiry
        for pos, expiry in state.get("temporary_obstacles", {}).items()
        if expiry > current_round
    }


def _should_force_opening_shell_yield(bot, ct: Controller, current_pos: Position) -> bool:
    core_pos = getattr(bot, "core_pos", None)
    if core_pos is None:
        return False
    if getattr(bot, "last_harvester_pos", None) is not None:
        return False
    if bot.builder_mode not in {BuilderMode.FINDING_ORE, BuilderMode.EXPLORING}:
        return False
    if ct.get_current_round() > 80:
        return False
    return utils.manhattan(current_pos, core_pos) <= 6


def _try_opening_shell_escape(bot, ct: Controller, current_pos: Position) -> bool:
    if not _should_force_opening_shell_yield(bot, ct, current_pos):
        return False

    core_pos = getattr(bot, "core_pos", None)
    if core_pos is None:
        return False

    temporary_obstacles = bot.pathfinding_state.get("temporary_obstacles", {})
    known_obstacles = bot.pathfinding_state.get("known_obstacles", set())
    movable_directions: list[tuple[Direction, Position]] = []
    adjacent_friendly_builders = 0

    for direction in utils.CARDINAL_DIRECTIONS:
        next_pos = current_pos.add(direction)
        next_key = (next_pos.x, next_pos.y)
        grid_entry = bot.grid.get(next_key, {})
        if (
            grid_entry.get("entity") == EntityType.BUILDER_BOT
            and grid_entry.get("entity_team") == ct.get_team()
        ):
            adjacent_friendly_builders += 1
            continue
        if not ct.can_move(direction):
            continue
        if next_key in known_obstacles or next_key in temporary_obstacles:
            continue
        movable_directions.append((direction, next_pos))

    if adjacent_friendly_builders < 2 or len(movable_directions) > 2:
        return False

    _, _, _, direction = max(
        (
            utils.manhattan(next_pos, core_pos),
            -next_pos.x,
            -next_pos.y,
            direction,
        )
        for direction, next_pos in movable_directions
    )
    ct.move(direction)
    return True


def _bresenham_line(start: Position, target: Position) -> set[tuple[int, int]]:
    x0, y0 = start.x, start.y
    x1, y1 = target.x, target.y
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    points: set[tuple[int, int]] = set()

    while True:
        points.add((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy

    return points


def _assault_target_tile_is_usable(
    tile_data: dict,
    my_team,
    *,
    allow_enemy_builder_at_target: bool,
) -> bool:
    entity_type = tile_data.get("entity")
    entity_team = tile_data.get("entity_team")
    if entity_type == EntityType.BUILDER_BOT:
        return entity_team != my_team and allow_enemy_builder_at_target
    if entity_type is not None and entity_type != EntityType.CORE:
        return False
    if entity_type == EntityType.CORE and entity_team != my_team:
        return False

    building_type = tile_data.get("building")
    building_team = tile_data.get("building_team")
    if building_type is None or building_type in PASSABLE_BUILDINGS:
        return True
    if building_type == EntityType.CORE and building_team == my_team:
        return True
    return (
        building_type in ASSAULT_CLEARABLE_TARGET_BUILDINGS
        and building_team is not None
        and building_team != my_team
    )


def _assault_is_walkable_tile(
    bot,
    ct: Controller,
    position: Position,
    target_pos: Position,
    *,
    allow_enemy_builder_at_target: bool,
    temporary_obstacles: set[tuple[int, int]],
) -> bool:
    return _assault_is_walkable_key(
        bot.grid,
        bot.pathfinding_state["known_obstacles"],
        (position.x, position.y),
        (target_pos.x, target_pos.y),
        map_w=ct.get_map_width(),
        map_h=ct.get_map_height(),
        my_team=ct.get_team(),
        allow_enemy_builder_at_target=allow_enemy_builder_at_target,
        temporary_obstacles=temporary_obstacles,
    )


def _assault_is_walkable_key(
    bot_grid: dict,
    known_obstacles: set[tuple[int, int]],
    key: tuple[int, int],
    target_key: tuple[int, int],
    *,
    map_w: int,
    map_h: int,
    my_team,
    allow_enemy_builder_at_target: bool,
    temporary_obstacles,
) -> bool:
    x, y = key
    if not (0 <= x < map_w and 0 <= y < map_h):
        return False

    tile_data = bot_grid.get(key, {})
    target_exception = key == target_key and _assault_target_tile_is_usable(
        tile_data,
        my_team,
        allow_enemy_builder_at_target=allow_enemy_builder_at_target,
    )

    if key != target_key and (key in known_obstacles or key in temporary_obstacles):
        return False

    env = tile_data.get("env")
    if env in IMPASSABLE_TILES:
        return False

    entity_type = tile_data.get("entity")
    entity_team = tile_data.get("entity_team")
    if entity_type == EntityType.BUILDER_BOT:
        if entity_team == my_team:
            return False
        return target_exception
    if entity_type is not None and entity_type != EntityType.CORE:
        return False
    if entity_type == EntityType.CORE and entity_team != my_team:
        return False

    building_type = tile_data.get("building")
    building_team = tile_data.get("building_team")
    if building_type is None or building_type in PASSABLE_BUILDINGS:
        return True
    if building_type == EntityType.CORE and building_team == my_team:
        return True
    return target_exception


def _ordered_assault_directions(
    current_pos: Position,
    target_pos: Position,
) -> list[Direction]:
    return sorted(
        ASSAULT_CLOCKWISE_DIRECTIONS,
        key=lambda direction: (
            max(
                abs(current_pos.x + ASSAULT_DIRECTION_DELTAS[direction][0] - target_pos.x),
                abs(current_pos.y + ASSAULT_DIRECTION_DELTAS[direction][1] - target_pos.y),
            ),
            abs(current_pos.x + ASSAULT_DIRECTION_DELTAS[direction][0] - target_pos.x)
            + abs(current_pos.y + ASSAULT_DIRECTION_DELTAS[direction][1] - target_pos.y),
            ASSAULT_DIRECTION_INDEX[direction],
        ),
    )


def _assault_bug_scan_directions(last_move_dir: Direction, side: int) -> list[Direction]:
    heading_index = ASSAULT_DIRECTION_INDEX[last_move_dir]
    if side < 0:
        start_index = (heading_index - 2) % len(ASSAULT_CLOCKWISE_DIRECTIONS)
        return [
            ASSAULT_CLOCKWISE_DIRECTIONS[
                (start_index + offset) % len(ASSAULT_CLOCKWISE_DIRECTIONS)
            ]
            for offset in range(len(ASSAULT_CLOCKWISE_DIRECTIONS))
        ]

    start_index = (heading_index + 2) % len(ASSAULT_CLOCKWISE_DIRECTIONS)
    return [
        ASSAULT_CLOCKWISE_DIRECTIONS[
            (start_index - offset) % len(ASSAULT_CLOCKWISE_DIRECTIONS)
        ]
        for offset in range(len(ASSAULT_CLOCKWISE_DIRECTIONS))
    ]


def _choose_local_assault_escape_direction(
    bot,
    ct: Controller,
    current_pos: Position,
    target_pos: Position,
    *,
    heading_dir: Direction,
    allow_enemy_builder_at_target: bool,
) -> Direction | None:
    temporary_obstacles = set(bot.pathfinding_state.get("temporary_obstacles", {}))
    candidates: list[tuple[int, int, int, int, Direction]] = []

    for side in (-1, 1):
        for direction in _assault_bug_scan_directions(heading_dir, side):
            if direction == heading_dir:
                continue
            nxt = current_pos.add(direction)
            if not _assault_is_walkable_tile(
                bot,
                ct,
                nxt,
                target_pos,
                allow_enemy_builder_at_target=allow_enemy_builder_at_target,
                temporary_obstacles=temporary_obstacles,
            ):
                continue
            if not ct.can_move(direction):
                continue

            candidates.append(
                (
                    max(abs(nxt.x - target_pos.x), abs(nxt.y - target_pos.y)),
                    abs(nxt.x - target_pos.x) + abs(nxt.y - target_pos.y),
                    0 if side < 0 else 1,
                    ASSAULT_DIRECTION_INDEX[direction],
                    direction,
                )
            )
            break

    if not candidates:
        return None
    return min(candidates)[-1]


def calculate_assault_bfs_path(
    bot,
    ct: Controller,
    start: Position,
    target: Position,
    *,
    allow_enemy_builder_at_target: bool = False,
    temporary_obstacles=None,
) -> list[tuple[ActionType, Direction]]:
    path, _, _ = _calculate_assault_bfs_result(
        bot,
        ct,
        start,
        target,
        allow_enemy_builder_at_target=allow_enemy_builder_at_target,
        temporary_obstacles=temporary_obstacles,
    )
    return path


def _calculate_assault_bfs_result(
    bot,
    ct: Controller,
    start: Position,
    target: Position,
    *,
    allow_enemy_builder_at_target: bool = False,
    temporary_obstacles=None,
) -> tuple[
    list[tuple[ActionType, Direction]],
    set[tuple[int, int]],
    dict[tuple[int, int], tuple[tuple[int, int], Direction] | None],
]:
    if start == target:
        return [], set(), {(start.x, start.y): None}

    _refresh_local_obstacle_memory(
        bot, start, bot.pathfinding_state["known_obstacles"], ct.get_team()
    )
    if temporary_obstacles is None:
        _expire_temporary_obstacles(bot.pathfinding_state, ct.get_current_round())
        temporary_obstacles = bot.pathfinding_state.get("temporary_obstacles", {})

    start_key = (start.x, start.y)
    target_key = (target.x, target.y)
    known_obstacles = bot.pathfinding_state["known_obstacles"]
    bot_grid = bot.grid
    map_w = ct.get_map_width()
    map_h = ct.get_map_height()
    my_team = ct.get_team()
    queue = deque([start_key])
    parents: dict[tuple[int, int], tuple[tuple[int, int], Direction] | None] = {
        start_key: None
    }
    preferred_dirs = _ordered_assault_directions(start, target)
    nodes_expanded = 0

    while queue and nodes_expanded < MAX_BFS_NODES:
        current_key = queue.popleft()
        nodes_expanded += 1
        if current_key == target_key:
            break

        for direction in preferred_dirs:
            ddx, ddy = ASSAULT_DIRECTION_DELTAS[direction]
            nxt_key = (current_key[0] + ddx, current_key[1] + ddy)
            if nxt_key in parents:
                continue
            if not _assault_is_walkable_key(
                bot_grid,
                known_obstacles,
                nxt_key,
                target_key,
                map_w=map_w,
                map_h=map_h,
                my_team=my_team,
                allow_enemy_builder_at_target=allow_enemy_builder_at_target,
                temporary_obstacles=temporary_obstacles,
            ):
                continue
            parents[nxt_key] = (current_key, direction)
            if nxt_key == target_key:
                queue.clear()
                break
            queue.append(nxt_key)

    _bump_stat(bot, "assault_bfs_replans")
    if target_key in parents:
        return _reconstruct_assault_path(start_key, target_key, parents), set(), parents
    return [], set(queue), parents


def _reconstruct_assault_path(
    start_key: tuple[int, int],
    end_key: tuple[int, int],
    parents: dict[tuple[int, int], tuple[tuple[int, int], Direction] | None],
) -> list[tuple[ActionType, Direction]]:
    path: list[tuple[ActionType, Direction]] = []
    key = end_key
    while key != start_key:
        parent_key, direction = parents[key]
        path.append((ActionType.CONVEYOR, direction))
        key = parent_key
    path.reverse()
    return path


def _mark_assault_temporary_obstacle(
    bot,
    key: tuple[int, int],
    current_round: int,
    *,
    ttl: int = ASSAULT_TEMP_OBSTACLE_TTL,
) -> None:
    bot.pathfinding_state.setdefault("temporary_obstacles", {})[key] = current_round + ttl


def _maybe_mark_dynamic_assault_obstacle(
    bot,
    ct: Controller,
    next_pos: Position,
    target_pos: Position,
    *,
    allow_enemy_builder_at_target: bool,
) -> None:
    next_key = (next_pos.x, next_pos.y)
    grid_entry = bot.grid.get(next_key, {})
    target_key = (target_pos.x, target_pos.y)

    if (
        grid_entry.get("entity") == EntityType.BUILDER_BOT
        and grid_entry.get("entity_team") == ct.get_team()
    ):
        other_bot_id = grid_entry.get("id")
        if (
            other_bot_id is not None and other_bot_id < ct.get_id()
        ) or _is_connected_to_harvester(bot, ct, next_pos):
            _mark_assault_temporary_obstacle(
                bot,
                next_key,
                ct.get_current_round(),
            )
        return

    if (
        grid_entry.get("entity") == EntityType.BUILDER_BOT
        and grid_entry.get("entity_team") is not None
        and grid_entry.get("entity_team") != ct.get_team()
    ):
        if not (allow_enemy_builder_at_target and next_key == target_key):
            _mark_assault_temporary_obstacle(
                bot,
                next_key,
                ct.get_current_round(),
            )
        return

    if not _assault_target_tile_is_usable(
        grid_entry,
        ct.get_team(),
        allow_enemy_builder_at_target=allow_enemy_builder_at_target,
    ):
        _mark_assault_temporary_obstacle(
            bot,
            next_key,
            ct.get_current_round(),
        )


def _execute_assault_move(
    bot,
    ct: Controller,
    move_dir: Direction,
    target_pos: Position,
    *,
    build_road: bool,
    allow_enemy_builder_at_target: bool,
) -> bool:
    next_pos = ct.get_position().add(move_dir)
    if build_road:
        utils.destroy_marker_if_present(ct, next_pos)
        if ct.can_build_road(next_pos):
            ct.build_road(next_pos)
    if ct.can_move(move_dir):
        ct.move(move_dir)
        return True

    _maybe_mark_dynamic_assault_obstacle(
        bot,
        ct,
        next_pos,
        target_pos,
        allow_enemy_builder_at_target=allow_enemy_builder_at_target,
    )
    return False


def _choose_frontier_path(
    frontier_nodes: set[tuple[int, int]],
    parents: dict[tuple[int, int], tuple[tuple[int, int], Direction] | None],
    *,
    start_key: tuple[int, int],
    target_pos: Position,
    temporary_obstacles: dict[tuple[int, int], int],
) -> tuple[list[tuple[ActionType, Direction]], tuple[int, int] | None, bool]:
    if not frontier_nodes:
        return [], None, False

    available_frontier = [key for key in frontier_nodes if key not in temporary_obstacles]
    if not available_frontier:
        return [], None, True

    frontier_key = min(
        available_frontier,
        key=lambda key: (
            max(abs(key[0] - target_pos.x), abs(key[1] - target_pos.y)),
            abs(key[0] - target_pos.x) + abs(key[1] - target_pos.y),
            key[0],
            key[1],
        ),
    )
    return (
        _reconstruct_assault_path(start_key, frontier_key, parents),
        frontier_key,
        False,
    )


def assault_navigate(
    bot,
    ct: Controller,
    target_pos: Position,
    *,
    build_road: bool = True,
    allow_enemy_builder_at_target: bool = False,
) -> tuple[bool, str | None]:
    current_pos = ct.get_position()
    if current_pos == target_pos:
        _assault_reset_navigation(bot, target_pos)
        return True, None

    _refresh_local_obstacle_memory(
        bot, current_pos, bot.pathfinding_state["known_obstacles"], ct.get_team()
    )
    _expire_temporary_obstacles(bot.pathfinding_state, ct.get_current_round())
    temporary_obstacles = bot.pathfinding_state.get("temporary_obstacles", {})

    state = getattr(bot, "assault_nav_state", None)
    if state is None:
        state = _assault_reset_navigation(bot, target_pos)

    target_key = (target_pos.x, target_pos.y)
    if state.get("current_target") != target_key:
        state = _assault_reset_navigation(bot, target_pos)

    bfs_path = _validate_assault_cached_bfs_path(
        bot,
        ct,
        current_pos,
        target_pos,
        allow_enemy_builder_at_target=allow_enemy_builder_at_target,
        temporary_obstacles=temporary_obstacles,
    )
    if bfs_path:
        _bump_stat(bot, "assault_bfs_cache_hits")
        state["bfs_path"] = bfs_path
        state["frontier_target"] = None
    else:
        bfs_path, frontier_nodes, parents = _calculate_assault_bfs_result(
            bot,
            ct,
            current_pos,
            target_pos,
            allow_enemy_builder_at_target=allow_enemy_builder_at_target,
            temporary_obstacles=temporary_obstacles,
        )
        if bfs_path:
            state["bfs_path"] = bfs_path
            state["frontier_target"] = None
        else:
            frontier_path, frontier_target, all_frontier_blocked = _choose_frontier_path(
                frontier_nodes,
                parents,
                start_key=(current_pos.x, current_pos.y),
                target_pos=target_pos,
                temporary_obstacles=temporary_obstacles,
            )
            if all_frontier_blocked:
                state["bfs_path"] = []
                state["frontier_target"] = None
                return False, None
            if not frontier_path:
                state["bfs_path"] = []
                state["frontier_target"] = None
                return False, "no_moves"
            state["bfs_path"] = frontier_path
            state["frontier_target"] = frontier_target

    bfs_path = state.get("bfs_path", [])
    if not bfs_path:
        return False, "no_moves"

    log_path(bot, ct, bfs_path)
    _, move_dir = bfs_path[0]
    if not _execute_assault_move(
        bot,
        ct,
        move_dir,
        target_pos,
        build_road=build_road,
        allow_enemy_builder_at_target=allow_enemy_builder_at_target,
    ):
        blocked_key = state.get("frontier_target")
        next_pos = current_pos.add(move_dir)
        blocked_tile = bot.grid.get((next_pos.x, next_pos.y), {})
        if blocked_key is None:
            blocked_key = (next_pos.x, next_pos.y)
        _mark_assault_temporary_obstacle(
            bot,
            blocked_key,
            ct.get_current_round(),
        )
        if blocked_tile.get("entity") == EntityType.BUILDER_BOT:
            escape_dir = _choose_local_assault_escape_direction(
                bot,
                ct,
                current_pos,
                target_pos,
                heading_dir=move_dir,
                allow_enemy_builder_at_target=allow_enemy_builder_at_target,
            )
            if escape_dir is not None and _execute_assault_move(
                bot,
                ct,
                escape_dir,
                target_pos,
                build_road=build_road,
                allow_enemy_builder_at_target=allow_enemy_builder_at_target,
            ):
                _bump_stat(bot, "assault_local_escape_moves")
                state["bfs_path"] = []
                state["frontier_target"] = None
                return True, "local_escape"
        state["bfs_path"] = []
        state["frontier_target"] = None
        if DEBUG_PATH_LOGGING:
            ct.draw_indicator_line(ct.get_position(), target_pos, 255, 140, 0)
        return False, "frontier_blocked"

    state["bfs_path"] = bfs_path[1:]
    if not state["bfs_path"]:
        state["frontier_target"] = None
    if DEBUG_PATH_LOGGING:
        ct.draw_indicator_line(ct.get_position(), target_pos, 0, 255, 0)
    return True, None


def assault_move_towards(
    bot,
    ct: Controller,
    target_pos: Position,
    *,
    build_road: bool = True,
    allow_enemy_builder_at_target: bool = False,
) -> bool:
    moved, _ = assault_navigate(
        bot,
        ct,
        target_pos,
        build_road=build_road,
        allow_enemy_builder_at_target=allow_enemy_builder_at_target,
    )
    return moved


def _validate_assault_cached_bfs_path(
    bot,
    ct: Controller,
    current_pos: Position,
    target_pos: Position,
    *,
    allow_enemy_builder_at_target: bool,
    temporary_obstacles,
) -> list[tuple[ActionType, Direction]]:
    state = getattr(bot, "assault_nav_state", None)
    if state is None:
        return []

    path = state.get("bfs_path", [])
    if not path:
        return []

    target_key = (target_pos.x, target_pos.y)
    known_obstacles = bot.pathfinding_state["known_obstacles"]
    bot_grid = bot.grid
    map_w = ct.get_map_width()
    map_h = ct.get_map_height()
    my_team = ct.get_team()
    simulated_x = current_pos.x
    simulated_y = current_pos.y
    blocked_index = None

    for idx, (_, direction) in enumerate(path[:A_STAR_LOOKAHEAD_CANCEL]):
        ddx, ddy = ASSAULT_DIRECTION_DELTAS[direction]
        simulated_x += ddx
        simulated_y += ddy
        step_key = (simulated_x, simulated_y)
        if not _assault_is_walkable_key(
            bot_grid,
            known_obstacles,
            step_key,
            target_key,
            map_w=map_w,
            map_h=map_h,
            my_team=my_team,
            allow_enemy_builder_at_target=allow_enemy_builder_at_target,
            temporary_obstacles=temporary_obstacles,
        ):
            if step_key != target_key:
                blocked_index = idx
                break

    if blocked_index is not None:
        if blocked_index == 0:
            path = []
        else:
            path = path[:blocked_index]

    state["bfs_path"] = path
    return path


def move_towards(
    bot,
    ct: Controller,
    target_pos: Position,
    cardinal_only: bool = False,
    allow_enemy_builder_at_target: bool = False,
) -> bool:
    if ct.get_position() == target_pos:
        return True
    moved, _ = try_pathfinding_move(
        bot,
        ct,
        target_pos,
        cardinal_only,
        throws_exception_on_failure=False,
        allow_enemy_builder_at_target=allow_enemy_builder_at_target,
    )
    if DEBUG_PATH_LOGGING:
        ct.draw_indicator_line(ct.get_position(), target_pos, 0, 255, 0)
    return moved


def _is_connected_to_harvester(bot, ct: Controller, start_pos: Position) -> bool:
    """Reverse trace conveyors to see if we're connected to a harvester (and thus can safely ignore it as an obstacle)."""
    utils.bump_profile(bot, "connected_harvester_checks")
    visited = set()
    to_visit = [start_pos]
    max_nodes = 16

    while to_visit and len(visited) < max_nodes:
        pos = to_visit.pop()
        if (pos.x, pos.y) in visited:
            continue
        visited.add((pos.x, pos.y))
        utils.bump_profile(bot, "connected_harvester_nodes")

        grid_entry = bot.grid.get((pos.x, pos.y), {})
        if grid_entry.get("entity") == EntityType.HARVESTER:
            utils.max_profile(bot, "connected_harvester_component_peak", len(visited))
            return True

        for d in utils.CARDINAL_DIRECTIONS:
            neighbor_pos = pos.add(d)
            neighbor_entry = bot.grid.get((neighbor_pos.x, neighbor_pos.y), {})
            if neighbor_entry.get("building") == EntityType.HARVESTER:
                utils.max_profile(bot, "connected_harvester_component_peak", len(visited))
                return True
            if (
                neighbor_entry.get("building")
                in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}
                and neighbor_entry.get("building_team") == ct.get_team()
            ):
                to_visit.append(neighbor_pos)

    utils.max_profile(bot, "connected_harvester_component_peak", len(visited))
    return False
