from cambc import Controller, EntityType, Position
from states import BuilderMode
import utils
import navigation

CAN_DESTROY_TYPES = {EntityType.MARKER, EntityType.ROAD, EntityType.CONVEYOR}


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
    return (
        target_kind == "core"
        and current_pos.distance_squared(target_pos) == 0
        and not bot.pending_build
    )


def _try_connect_to_conveyor(
    bot, ct: Controller, current_pos: Position, target_pos: Position, target_kind: str
) -> bool:
    """Attempts to merge the new conveyor line into an existing conveyor line."""
    if (
        target_kind != "conveyor"
        or utils.manhattan(current_pos, target_pos) != 1
        or bot.pending_build
    ):
        return False

    connect_dir = current_pos.direction_to(target_pos)

    if not ct.can_build_conveyor(current_pos, connect_dir):
        if (
            ct.can_destroy(current_pos)
            and ct.get_entity_type(ct.get_tile_building_id(current_pos))
            in CAN_DESTROY_TYPES
        ):
            bot.logger.log(f"destroying building at {current_pos} to build conveyor")
            ct.destroy(current_pos)

    if ct.can_build_conveyor(current_pos, connect_dir):
        bot.logger.log(f"tiling back, connecting to nearby conveyor at {target_pos}")
        ct.build_conveyor(current_pos, connect_dir)
        bot.tiled_back_positions.add(current_pos)
        return True
    elif (
        ct.get_entity_type(ct.get_tile_building_id(current_pos)) in CAN_DESTROY_TYPES
        and ct.get_direction(ct.get_tile_building_id(current_pos)) == connect_dir
    ):
        return True

    return False


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
        bot.logger.log("still can't execute pending build, maybe blocked?")
    return True


def _clear_obstacles_for_conveyor(ct: Controller, current_pos: Position, move_dir):
    """Destroys markers, roads, or misaligned conveyors to make way for the new path."""
    id = ct.get_tile_building_id(current_pos)
    if ct.can_destroy(current_pos):
        if ct.get_entity_type(id) in [EntityType.MARKER, EntityType.ROAD]:
            ct.destroy(current_pos)
        elif (
            ct.get_entity_type(id) in CAN_DESTROY_TYPES
            and ct.get_direction(id) != move_dir
        ):
            ct.destroy(current_pos)


def _navigate_and_build(
    bot, ct: Controller, current_pos: Position, target_pos: Position
):
    """Uses bugnav to move toward the target while laying conveyors pointing backward."""
    move_dir = navigation.get_bugnav_dir(
        bot, ct, current_pos, target_pos, utils.CARDINAL_DIRECTIONS
    )
    if move_dir is None:
        return

    if not ct.can_build_conveyor(current_pos, move_dir):
        _clear_obstacles_for_conveyor(ct, current_pos, move_dir)

    can_move = navigation.try_bugnav_move(
        bot, ct, target_pos, utils.CARDINAL_DIRECTIONS
    )

    if can_move:
        if ct.can_build_conveyor(current_pos, move_dir):
            ct.build_conveyor(current_pos, move_dir)
            bot.tiled_back_positions.add(current_pos)
        else:
            building_id_at_conveyor = ct.get_tile_building_id(current_pos)

            # TODO: evaluate, due to other objects
            # we force ourselves to build the conveyor if the reason we can't build is that there's a
            # non-conveyor building in the way and we have enough resources, otherwise we might get stuck
            # in a loop where we can't move or build
            if building_id_at_conveyor is None or (
                ct.get_entity_type(building_id_at_conveyor) in CAN_DESTROY_TYPES
                and ct.get_global_resources() < ct.get_conveyor_cost()
            ):
                bot.pending_build = (current_pos, move_dir)
    else:
        # Can't move, try to build ahead
        next_pos = current_pos.add(move_dir)
        next_pos_best_dir = navigation.get_bugnav_dir(
            bot, ct, next_pos, target_pos, utils.CARDINAL_DIRECTIONS
        )

        if next_pos_best_dir is not None and ct.can_build_conveyor(
            next_pos, next_pos_best_dir
        ):
            ct.build_conveyor(next_pos, next_pos_best_dir)
            bot.tiled_back_positions.add(next_pos)


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

    # 1. Check End Conditions
    if _is_at_core(bot, current_pos, target_pos, target_kind):
        bot.builder_mode = BuilderMode.FINDING_ORE
        return

    if _try_connect_to_conveyor(bot, ct, current_pos, target_pos, target_kind):
        bot.builder_mode = BuilderMode.FINDING_ORE
        return

    # 2. Check Pending Actions
    if _execute_pending_build(bot, ct):
        return

    # 3. Main Action: Move and Build
    _navigate_and_build(bot, ct, current_pos, target_pos)
