from cambc import Controller, EntityType, Position
from states import BuilderMode
import utils
import navigation

CAN_DESTROY_TYPES = {EntityType.MARKER, EntityType.ROAD, None}


def _update_return_target_while_tiling(bot, current_pos: Position):
    """Recalculates the closest drop-off point (core or friendly conveyor) as the bot moves."""
    core_target = utils.closest_point_on_grid(bot.core_pos, current_pos)
    best_target = core_target
    best_dist = utils.manhattan(current_pos, core_target)
    best_kind = "core"

    conveyor_candidates = [
        c
        for c in bot.known_friendly_conveyors
        if c != current_pos and c not in bot.tiled_back_positions
    ]
    if conveyor_candidates:
        nearest_c = min(
            conveyor_candidates, key=lambda c_pos: utils.manhattan(current_pos, c_pos)
        )
        nearest_c_dist = utils.manhattan(current_pos, nearest_c)
        if nearest_c_dist < best_dist:
            best_target = nearest_c
            best_dist = nearest_c_dist
            best_kind = "conveyor"

    bot.return_target_pos = best_target
    bot.return_target_dist_manhatten = best_dist
    bot.return_target_kind = best_kind
    bot.nearest_conveyor_pos = best_target if best_kind == "conveyor" else None
    bot.nearest_conveyor_dist_manhatten = (
        best_dist if best_kind == "conveyor" else float("inf")
    )


def _is_at_core(
    bot, current_pos: Position, target_pos: Position, target_kind: str
) -> bool:
    """Checks if the bot has successfully tiled back to the core."""
    # print(
    #     f"checking at core: target {target_pos}, current {current_pos}, pending build {bot.pending_build}"
    # )
    return (
        target_kind == "core"
        and utils.manhattan(current_pos, target_pos) == 0
        and not bot.pending_build
    )


def _check_connect_to_conveyor(
    bot, current_pos: Position, target_pos: Position, target_kind: str
) -> bool:
    # print(
    #     f"checking conveyor connection: target {target_pos}, current {current_pos}, pending build {bot.pending_build}"
    # )
    if (
        target_kind != "conveyor"
        or utils.manhattan(current_pos, target_pos) > 0
        or bot.pending_build
    ):
        return False

    return True


def _execute_pending_build(bot, ct: Controller) -> bool:
    """Executes a queued build order if resources or obstacles previously prevented it."""
    if bot.pending_build is None:
        return False

    build_pos, build_dir = bot.pending_build
    if ct.can_build_conveyor(build_pos, build_dir):
        bot.logger.log(
            f"executing pending build of conveyor at {build_pos} toward {build_dir}"
        )
        ct.build_conveyor(build_pos, build_dir)
        bot.tiled_back_positions.add(build_pos)
        bot.pending_build = None
    else:
        _clear_obstacles_for_conveyor(ct, build_pos, build_dir)
        bot.logger.log("still can't execute pending build, maybe blocked?")
    return True


def _clear_obstacles_for_conveyor(
    ct: Controller, current_pos: Position, build_dir: Position
):
    """Destroys markers, roads, or misaligned conveyors to make way for the new path."""
    if utils.get_tile_building_entity_type(ct, current_pos) in CAN_DESTROY_TYPES or (
        utils.get_tile_building_entity_type(ct, current_pos) == EntityType.CONVEYOR
        and ct.get_direction(ct.get_tile_building_id(current_pos)) != build_dir
    ):
        if ct.can_destroy(current_pos):
            ct.destroy(current_pos)


def _navigate_and_build(
    bot, ct: Controller, current_pos: Position, target_pos: Position
):
    """Uses A* memory to look ahead and build conveyors pointing backward."""

    # 1. Ask the brain what the plan is (Zero execution yet)
    move_dir, next_state = navigation.compute_pathfinding_step(
        bot,
        ct,
        current_pos,
        target_pos,
        bot.pathfinding_state,
        prioritize_cardinal=True,
    )

    if move_dir is None:
        return

    # 2. Lookahead
    # Since move_dir was popped from next_state["path"], the NEW first
    # element in the path list is exactly where we will go on the turn AFTER this one.
    next_pos_best_dir = next_state["path"][0] if next_state["path"] else None
    next_pos = current_pos.add(move_dir)

    # 3. Clear obstacles for our immediate move
    if not ct.can_build_conveyor(current_pos, move_dir):
        _clear_obstacles_for_conveyor(ct, current_pos, move_dir)

    # 4. Lookahead Building: If we are stuck right now, try to build ahead of ourselves!
    if not ct.can_move(move_dir) and next_pos_best_dir is not None:
        if ct.can_build_conveyor(next_pos, next_pos_best_dir):
            ct.build_conveyor(next_pos, next_pos_best_dir)
            bot.tiled_back_positions.add(next_pos)

    # 5. Execute the actual move (We bypass try_pathfinding_move's internal compute
    # to avoid double-calculating, handling it manually right here for ultimate speed).

    moved_successfully = False
    if ct.can_move(move_dir):
        ct.move(move_dir)
        bot.pathfinding_state = next_state  # Commit the memory!
        moved_successfully = True
    # Stumped fallback ignored, we are guaranteed passable, so we wait for the
    # other to get out of the way
    # else:
    # bot.pathfinding_state["known_obstacles"].add((next_pos.x, next_pos.y))
    # bot.pathfinding_state["path"] = []

    # 6. Build under ourselves (whether we moved or just cleared space)
    if ct.can_build_conveyor(current_pos, move_dir):
        ct.build_conveyor(current_pos, move_dir)
        bot.tiled_back_positions.add(current_pos)
    elif moved_successfully:
        # We couldn't build it, and we moved. Queue it up so we force build on next turn
        # before continuing to move
        if utils.get_tile_building_entity_type(ct, current_pos) in CAN_DESTROY_TYPES:
            bot.pending_build = (current_pos, move_dir)


def execute(bot, ct: Controller):
    current_pos = ct.get_position()
    _update_return_target_while_tiling(bot, current_pos)

    target_pos = (
        bot.return_target_pos if bot.return_target_pos is not None else bot.core_pos
    )
    target_kind = bot.return_target_kind

    if target_kind == "core":
        target_pos = utils.closest_point_on_grid(bot.core_pos, current_pos)

    bot.logger.log(
        f"state: pending build {bot.pending_build}, return target {bot.return_target_pos}, kind {bot.return_target_kind}"
    )

    # 1. Check Pending Actions
    executed = _execute_pending_build(bot, ct)

    # 2. Main Action: Move and Build
    if not executed:
        _navigate_and_build(bot, ct, current_pos, target_pos)

    # 3. Check End Conditions
    current_pos = ct.get_position()
    if _is_at_core(bot, current_pos, target_pos, target_kind):
        bot.builder_mode = BuilderMode.FINDING_ORE
        return

    if _check_connect_to_conveyor(bot, current_pos, target_pos, target_kind):
        bot.builder_mode = BuilderMode.FINDING_ORE
        return
