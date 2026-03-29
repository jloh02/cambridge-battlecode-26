import heapq
import utils
from states import BuilderMode
from cambc import Controller, Direction, Position


def get_sweep_dirs(
    heading: Direction, side: int, valid_directions: list[Direction]
) -> list[Direction]:
    curr = heading
    for _ in range(3):
        curr = curr.rotate_right() if side == 1 else curr.rotate_left()

    sweep = []
    for _ in range(7):
        if curr in valid_directions:
            sweep.append(curr)
        curr = curr.rotate_left() if side == 1 else curr.rotate_right()
    return sweep


DIAGONAL_COST = 5.05
CARDINAL_COST = 1.0
DEFAULT_COST = 1.0


def get_cost_weights(proritize_cardinal: bool = False) -> list[tuple[Direction, float]]:
    if proritize_cardinal:
        return [(d, CARDINAL_COST) for d in utils.CARDINAL_DIRECTIONS] + [
            (d, DIAGONAL_COST) for d in utils.DIAGONAL_DIRECTIONS
        ]
    return [(d, DEFAULT_COST) for d in utils.DIAGONAL_DIRECTIONS] + [
        (d, DEFAULT_COST) for d in utils.CARDINAL_DIRECTIONS
    ]


def calculate_astar_path(
    start: Position,
    target: Position,
    known_obstacles: set[tuple[int, int]],
    prioritize_cardinal: bool = False,
) -> list[Direction]:
    """Calculates the lowest-cost path from start to target considering known walls."""

    # Priority Queue: stores (f_cost, counter, position, path_history)
    open_set = []
    heapq.heappush(open_set, (0, 0, start, []))

    # Tracks the absolute lowest cost to reach any specific tile
    g_costs = {(start.x, start.y): 0}
    counter = 1  # Tie-breaker for the priority queue

    while open_set:
        f_cost, _, current, path = heapq.heappop(open_set)

        # Did we reach the target?
        if current.x == target.x and current.y == target.y:
            return path

        # Generate all possible moves and their costs
        moves = get_cost_weights(prioritize_cardinal)

        for direction, cost in moves:
            neighbor = current.add(direction)
            pos_tuple = (neighbor.x, neighbor.y)

            # Do not step into known walls
            if pos_tuple in known_obstacles:
                continue

            new_g_cost = g_costs[(current.x, current.y)] + cost

            # If this is the first time seeing this tile, OR we found a cheaper way to it
            if pos_tuple not in g_costs or new_g_cost < g_costs[pos_tuple]:
                g_costs[pos_tuple] = new_g_cost

                # Heuristic: Manhattan Distance (perfectly admissible since our lowest cost is 1)
                h_cost = abs(neighbor.x - target.x) + abs(neighbor.y - target.y)

                new_path = list(path)
                new_path.append(direction)

                heapq.heappush(
                    open_set, (new_g_cost + h_cost, counter, neighbor, new_path)
                )
                counter += 1

    return []  # No path found


def compute_pathfinding_step(
    ct: Controller,
    current_pos: Position,
    target_pos: Position,
    current_state: dict,
    prioritize_cardinal: bool = False,
) -> tuple[Direction | None, dict]:

    state = current_state.copy()

    # Initialize bot memory if it doesn't exist
    if "known_obstacles" not in state:
        state["known_obstacles"] = set()
    if "path" not in state:
        state["path"] = []

    # 1. Update memory based on immediate vision
    # (Assuming we can "see" all immediately adjacent tiles)
    for d in utils.CARDINAL_DIRECTIONS + utils.DIAGONAL_DIRECTIONS:
        neighbor_pos = current_pos.add(d)
        if not utils.is_passable(ct, current_pos, d):
            state["known_obstacles"].add((neighbor_pos.x, neighbor_pos.y))

    # 2. Validate current path
    if state["path"]:
        next_dir = state["path"][0]
        next_pos = current_pos.add(next_dir)

        # If the next step in our plan is now known to be a wall, trash the path
        if (next_pos.x, next_pos.y) in state["known_obstacles"]:
            state["path"] = []

    # 3. Calculate a new path if we don't have one
    if not state["path"]:
        state["path"] = calculate_astar_path(
            current_pos,
            target_pos,
            state["known_obstacles"],
            prioritize_cardinal,
        )

    # 4. Extract the next step
    move_dir = None
    if state["path"]:
        move_dir = state["path"].pop(0)  # Remove and return the first step

    return move_dir, state


def try_pathfinding_move(
    bot, ct: Controller, target_pos: Position, prioritize_cardinal: bool = False
) -> bool:
    current_pos = ct.get_position()

    # Get our predictive move and updated memory
    move_dir, new_state = compute_pathfinding_step(
        ct,
        current_pos,
        target_pos,
        bot.pathfinding_state,  # (Make sure you initialize this as an empty {} on bot creation)
        prioritize_cardinal,
    )

    if move_dir is None:
        return False

    next_pos = current_pos.add(move_dir)
    is_jump = move_dir in utils.DIAGONAL_DIRECTIONS

    # 1. Handle Building Logic (Roads vs Jumps)
    if is_jump:
        # We need a custom jump builder here!
        if hasattr(ct, "can_build_jump") and ct.can_build_jump(next_pos):
            ct.build_jump(next_pos)
            # Add to tiled back positions if needed
    else:
        # Normal Cardinal Road Building
        if bot.builder_mode != BuilderMode.TILING_BACK and ct.can_build_road(next_pos):
            ct.build_road(next_pos)

    # 2. Execute Move
    if ct.can_move(move_dir):
        ct.move(move_dir)

        # ONLY save the state if the physical move succeeded!
        bot.pathfinding_state = new_state
        return True

    # 3. The "Stumped" Fallback (CRITICAL)
    # If can_move fails, the bot bumped into an unpredicted wall.
    # Add it to memory and wipe the path to force a recalculation!
    bot.pathfinding_state["known_obstacles"].add((next_pos.x, next_pos.y))
    bot.pathfinding_state["path"] = []

    return False


def move_towards(
    bot, ct: Controller, target_pos: Position, prioritize_cardinal: bool = False
):
    if ct.get_position() == target_pos:
        return
    ct.draw_indicator_dot(target_pos, 0, 255, 0)
    try_pathfinding_move(bot, ct, target_pos, prioritize_cardinal)
