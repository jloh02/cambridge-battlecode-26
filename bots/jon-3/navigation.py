import heapq
import utils
from states import BuilderMode, ActionType
from cambc import Controller, Direction, Position

DIAGONAL_COST = 50.00  # Set very high to discourage jumps unless necessary
CARDINAL_COST = 1.0
DEFAULT_COST = 1.0
BRIDGE_COST = 20.0

A_STAR_ITERATION_LIMIT = 1000

BRIDGE_OFFSETS = []
for dx in range(-3, 4):
    for dy in range(-3, 4):
        dist_sq = dx**2 + dy**2
        # Exclude 1 (cardinal conveyor) and 0 (current tile)
        # Includes diagonals (d^2 = 2) up to max jump (d^2 = 9)
        if 1 < dist_sq <= 9:
            BRIDGE_OFFSETS.append((Position(dx, dy), BRIDGE_COST))


def get_cost_weights(
    prioritize_cardinal: bool = False,
) -> list[tuple[Direction, float]]:
    if prioritize_cardinal:
        return [(d, CARDINAL_COST) for d in utils.CARDINAL_DIRECTIONS] + [
            (d, DIAGONAL_COST) for d in utils.DIAGONAL_DIRECTIONS
        ]
    return [(d, DEFAULT_COST) for d in utils.DIRECTIONS]


def calculate_astar_path(
    bot,
    start: Position,
    target: Position,
    known_obstacles: set[tuple[int, int]],
    prioritize_cardinal: bool = False,
    allow_bridges: bool = True,
) -> list[Direction]:
    """Calculates the lowest-cost path from start to target considering known walls."""

    open_set = []
    heapq.heappush(open_set, (0, 0, start, []))
    g_costs = {(start.x, start.y): 0}
    counter = 1
    iterations = 0

    while open_set and iterations < A_STAR_ITERATION_LIMIT:
        f_cost, _, current, path = heapq.heappop(open_set)

        if current.x == target.x and current.y == target.y:
            return path

        iterations += 1

        # --- 1. Conveyor Routing (Standard) ---
        moves = get_cost_weights(prioritize_cardinal)
        for direction, cost in moves:
            neighbor = current.add(direction)
            pos_tuple = (neighbor.x, neighbor.y)

            if pos_tuple in known_obstacles:
                continue

            _push_to_astar(
                open_set,
                g_costs,
                current,
                neighbor,
                target,
                cost,
                (ActionType.CONVEYOR, direction),
                path,
                counter,
            )
            counter += 1

        # --- 2. Bridge Routing (Bypass) ---
        # ONLY process bridges if the boolean flag allows it
        if allow_bridges and bot.builder_mode == BuilderMode.TILING_BACK:
            for offset, cost in BRIDGE_OFFSETS:
                neighbor = Position(current.x + offset.x, current.y + offset.y)
                pos_tuple = (neighbor.x, neighbor.y)

                if pos_tuple in known_obstacles and pos_tuple != (target.x, target.y):
                    continue

                _push_to_astar(
                    open_set,
                    g_costs,
                    current,
                    neighbor,
                    target,
                    cost,
                    (ActionType.BRIDGE, neighbor),
                    path,
                    counter,
                )
                counter += 1

    bot.logger.print(f"A* unable to find path ({iterations} iterations)")
    return []


def _push_to_astar(
    open_set,
    g_costs,
    current,
    neighbor,
    target,
    cost,
    action_tuple,
    path,
    counter,
    use_chebyshev=True,
):
    new_g_cost = g_costs[(current.x, current.y)] + cost
    pos_tuple = (neighbor.x, neighbor.y)

    if pos_tuple not in g_costs or new_g_cost < g_costs[pos_tuple]:
        g_costs[pos_tuple] = new_g_cost

        if use_chebyshev:
            h_cost = max(abs(neighbor.x - target.x), abs(neighbor.y - target.y))
        else:
            h_cost = abs(neighbor.x - target.x) + abs(neighbor.y - target.y)

        new_path = list(path)
        new_path.append(action_tuple)

        heapq.heappush(open_set, (new_g_cost + h_cost, counter, neighbor, new_path))


def compute_pathfinding_step(
    bot,
    ct: Controller,
    current_pos: Position,
    target_pos: Position,
    current_state: dict,
    prioritize_cardinal: bool = False,
) -> tuple[Direction | None, dict]:
    state = current_state.copy()

    state["path"] = list(state["path"])

    # 1. Clean up expired temporary obstacles
    active_temp_obs = {
        pos: expiry
        for pos, expiry in state.get("temporary_obstacles", {}).items()
        if expiry > ct.get_current_round()
    }
    state["temporary_obstacles"] = active_temp_obs

    # Combine known walls with active temporary obstacles
    all_obstacles = state["known_obstacles"].union(set(active_temp_obs.keys()))

    # 2. Update memory based on immediate vision
    for d in utils.DIRECTIONS:
        neighbor_pos = current_pos.add(d)
        if not utils.is_passable(ct, current_pos, d):
            state["known_obstacles"].add((neighbor_pos.x, neighbor_pos.y))

    # Invalidate path if the target has changed!
    target_tuple = (target_pos.x, target_pos.y)
    if state.get("current_target") != target_tuple:
        state["path"] = []
        state["current_target"] = target_tuple

    # 3. Validate current path against ALL obstacles
    if state["path"]:
        next_action = state["path"][0]
        next_type, next_val = next_action

        if next_type == ActionType.CONVEYOR:
            next_dir = next_val
            next_pos = current_pos.add(next_dir)
        elif next_type == ActionType.BRIDGE:
            next_pos = next_val

        if (next_pos.x, next_pos.y) in all_obstacles:
            state["path"] = []

    # 4. Calculate a new path using ALL obstacles
    if not state["path"]:
        state["path"] = calculate_astar_path(
            bot,
            current_pos,
            target_pos,
            all_obstacles,  # Pass the combined set here!
            prioritize_cardinal,
        )

    # 5. Extract the next step
    move_dir = None
    if state["path"]:
        move_dir = state["path"].pop(0)

    log_path(bot, ct, state["path"])
    bot.logger.log(f"Next move: {move_dir})")

    return move_dir, state


def log_path(bot, ct, path):
    path_coords = []
    current_pos = ct.get_position()
    for action in path:
        action_type, action_val = action
        if action_type == ActionType.CONVEYOR:
            current_pos = current_pos.add(action_val)
        elif action_type == ActionType.BRIDGE:
            current_pos = action_val
        path_coords.append(f"{action_type}({current_pos.x},{current_pos.y})")
    path_str = " -> ".join(path_coords)
    bot.logger.log(f"Computed Path: {path_str}")


def try_pathfinding_move(
    bot, ct: Controller, target_pos: Position, prioritize_cardinal: bool = False
) -> tuple[bool, Position]:
    """
    Executes a move and updates memory.
    Returns: (Success Boolean, Current Position of the Bot)
    """
    current_pos = ct.get_position()

    bot.logger.log(
        f"Current obstacles: {bot.pathfinding_state.get('known_obstacles', set())}"
    )
    bot.logger.log(
        f"Current temporary obstacles: {bot.pathfinding_state.get('temporary_obstacles', {})}"
    )

    move_action, new_state = compute_pathfinding_step(
        bot,
        ct,
        current_pos,
        target_pos,
        bot.pathfinding_state,
        prioritize_cardinal,
    )

    if move_action is None:
        return False, current_pos

    action_type, action_val = move_action
    if action_type == ActionType.BRIDGE:
        next_pos = action_val
    else:
        move_dir = action_val
        next_pos = current_pos.add(action_val)
    # is_jump = move_dir in utils.DIAGONAL_DIRECTIONS

    # TODO bridge
    # 1. Handle Jumps (Since roads are handled in _navigate_and_build)
    # if is_jump:
    #     if hasattr(ct, "can_build_jump") and ct.can_build_jump(next_pos):
    #         ct.build_jump(next_pos)
    # else:
    if bot.builder_mode != BuilderMode.TILING_BACK and ct.can_build_road(next_pos):
        ct.build_road(next_pos)

    # 2. Execute Move
    if ct.can_move(move_dir):
        ct.move(move_dir)
        # ONLY save the state if the physical move succeeded!
        bot.pathfinding_state = new_state
        return True, ct.get_position()

    # 3. The "Stumped" Fallback
    bot.pathfinding_state.setdefault("temporary_obstacles", {})[
        (next_pos.x, next_pos.y)
    ] = (ct.get_current_round() + 3)
    return False, current_pos


def move_towards(
    bot, ct: Controller, target_pos: Position, prioritize_cardinal: bool = False
):
    if ct.get_position() == target_pos:
        return
    ct.draw_indicator_dot(target_pos, 0, 255, 0)
    try_pathfinding_move(bot, ct, target_pos, prioritize_cardinal)
