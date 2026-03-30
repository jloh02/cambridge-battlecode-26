from cambc import Controller, EntityType, Position, GameConstants
from states import BuilderMode, TargetKind, ActionType
import utils
import navigation

CAN_DESTROY_TYPES = {EntityType.MARKER, EntityType.ROAD, None}


def _update_return_target_while_tiling(bot, ct: Controller, current_pos: Position):
    """Recalculates the closest drop-off point (core or friendly conveyor) as the bot moves."""
    core_target = utils.closest_point_on_grid(bot.core_pos, current_pos)
    best_target = core_target
    best_dist = utils.manhattan(current_pos, core_target)
    best_kind = TargetKind.CORE

    conveyor_candidates = [
        c
        for c in bot.known_friendly_conveyors
        if c != current_pos
        and c not in bot.tiled_back_positions
        and _is_connected_to_core(bot, ct, c)
    ]
    if conveyor_candidates:
        nearest_c = min(
            conveyor_candidates, key=lambda c_pos: utils.manhattan(current_pos, c_pos)
        )
        nearest_c_dist = utils.manhattan(current_pos, nearest_c)
        if nearest_c_dist < best_dist:
            best_target = nearest_c
            best_dist = nearest_c_dist
            best_kind = TargetKind.CONVEYOR

    bot.return_target_pos = best_target
    bot.return_target_dist_manhatten = best_dist
    bot.return_target_kind = best_kind
    bot.nearest_conveyor_pos = best_target if best_kind == TargetKind.CONVEYOR else None
    bot.nearest_conveyor_dist_manhatten = (
        best_dist if best_kind == TargetKind.CONVEYOR else float("inf")
    )


def _is_connected_to_core(bot, ct: Controller, start_pos: Position) -> bool:
    """Traces the conveyor network in memory to verify it reaches the core."""
    current = start_pos
    visited = set()

    while current:
        pos_tuple = (current.x, current.y)

        # 1. Check if we've reached the core
        # Adjust distance check depending on if conveyors must point directly INTO the core tile
        # or just be adjacent to it.
        if utils.manhattan(current, bot.core_pos) <= 1:
            return True

        # 2. Cycle detection
        if pos_tuple in visited:
            return False
        visited.add(pos_tuple)

        # 3. Read from memory
        grid_data = bot.grid.get(pos_tuple, {})
        building = grid_data.get("building")

        # If the chain breaks or it's not a friendly conveyor, the path is invalid
        if (
            building not in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}
            or grid_data.get("building_team") != ct.get_team()
        ):
            return False

        # 4. Move to the next tile based on the conveyor's direction
        b_dir = grid_data.get("building_dir")
        if not b_dir:
            return False  # Missing direction data, can't trust the path

        current = current.add(b_dir)

    return False


def _is_at_core(
    bot, current_pos: Position, target_pos: Position, target_kind: str
) -> bool:
    """Checks if the bot has successfully tiled back to the core."""
    # print(
    #     f"checking at core: target {target_pos}, current {current_pos}, pending build {bot.pending_build}"
    # )
    return (
        target_kind == TargetKind.CORE
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
        target_kind != TargetKind.CONVEYOR
        or utils.manhattan(current_pos, target_pos) > 0
        or bot.pending_build
    ):
        return False

    return True


def _execute_pending_build(bot, ct: Controller) -> bool:
    """Executes a queued build order if resources or obstacles previously prevented it."""
    if bot.pending_build is None:
        return False

    action_type = bot.pending_build[0]

    if action_type == ActionType.CONVEYOR:
        _, build_pos, build_dir = bot.pending_build
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

    elif action_type == ActionType.BRIDGE:
        _, start_pos, target_pos = bot.pending_build
        if ct.can_build_bridge(start_pos, target_pos):
            bot.logger.log(
                f"executing pending build of bridge from {start_pos} to {target_pos}"
            )
            ct.build_bridge(start_pos, target_pos)
            bot.tiled_back_positions.add(start_pos)
            bot.tiled_back_positions.add(target_pos)
            bot.pending_build = None
        else:
            _clear_obstacles_for_conveyor(ct, start_pos, None)
            bot.logger.log("blocked from building pending bridge, waiting...")
        return True

    return False


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

    if bot.bridge_transit_path:
        action_type, move_dir = bot.bridge_transit_path[0]

        bot.logger.log("Currently in bridge transit")
        navigation.log_path(bot, ct, bot.bridge_transit_path)

        if not ct.can_move(move_dir):
            next_pos = current_pos.add(move_dir)
            if ct.can_build_road(next_pos):
                ct.build_road(next_pos)

        if ct.can_move(move_dir):
            ct.move(move_dir)
            bot.bridge_transit_path.pop(0)

            # Queue the bridge build now that we are out of the way
            bridge_start = getattr(bot, "pending_bridge_start", None)
            bridge_end = getattr(bot, "pending_bridge_end", None)
            if (
                bridge_start
                and bridge_end
                and ct.get_position().distance_squared(bridge_start) <= 2
            ):
                bot.pending_build = (ActionType.BRIDGE, bridge_start, bridge_end)

            # If we just took the last step of the transit path, we arrived!
            if not bot.bridge_transit_path:
                bot.logger.log(
                    "Bridge transit complete. Queueing bridge build behind us."
                )

                # Restore the master path to continue building
                bot.pathfinding_state["path"] = getattr(
                    bot, "saved_post_bridge_path", []
                )
                bot.saved_post_bridge_path = []

        return  # Suspend all complex A* thinking until we finish crossing

    # 1. Ask the brain what the plan is
    move_action, next_state = navigation.compute_pathfinding_step(
        bot,
        ct,
        current_pos,
        target_pos,
        bot.pathfinding_state,
        prioritize_cardinal=True,
    )

    if move_action is None:
        return

    action_type, action_val = move_action

    if action_type == ActionType.BRIDGE:
        jump_target_pos = action_val
        bot.logger.log(
            f"Master Path requires bridge from {current_pos} to {jump_target_pos}. Initiating transit."
        )

        # 1. Save the rest of the master route
        bot.saved_post_bridge_path = next_state["path"]
        bot.pending_bridge_start = current_pos
        bot.pending_bridge_end = jump_target_pos

        # 2. Calculate physical walking route (Bot uses diagonals, no bridges)
        bot.bridge_transit_path = navigation.calculate_astar_path(
            bot,
            start=current_pos,
            target=jump_target_pos,
            known_obstacles=bot.pathfinding_state["known_obstacles"],
            prioritize_cardinal=False,  # Allow for diagonals so the bot jumps the gap
            allow_bridges=False,
        )

        # 3. Advance the pathfinding memory so it doesn't try to recompute the bridge
        bot.pathfinding_state = next_state

    elif action_type == ActionType.CONVEYOR:
        move_dir = action_val
        next_action = next_state["path"][0] if next_state["path"] else None

        if not ct.can_build_conveyor(current_pos, move_dir):
            _clear_obstacles_for_conveyor(ct, current_pos, move_dir)

        # Lookahead Building
        if not ct.can_move(move_dir) and next_action is not None:
            next_action_type, next_pos_best_dir = next_action
            next_pos = current_pos.add(move_dir)

            if next_action_type == ActionType.CONVEYOR:
                if ct.can_build_conveyor(next_pos, next_pos_best_dir):
                    ct.build_conveyor(next_pos, next_pos_best_dir)
                    bot.tiled_back_positions.add(next_pos)
            elif next_action_type == ActionType.BRIDGE:
                jump_target_pos = next_pos_best_dir
                # Note: If it builds ahead, it builds it BEFORE arriving. If this happens
                # frequently and traps you, you may want to remove this specific lookahead block.
                if ct.can_build_bridge(next_pos, jump_target_pos):
                    ct.build_bridge(next_pos, jump_target_pos)
                    bot.tiled_back_positions.add(next_pos)
                    next_state["known_obstacles"].discard((next_pos.x, next_pos.y))
                    bot.pathfinding_state = next_state

        # Execute move
        moved_successfully = False
        if ct.can_move(move_dir):
            ct.move(move_dir)
            bot.pathfinding_state = next_state
            moved_successfully = True

        # Build under ourselves
        if ct.can_build_conveyor(current_pos, move_dir):
            ct.build_conveyor(current_pos, move_dir)
            bot.tiled_back_positions.add(current_pos)
        elif moved_successfully:
            if (
                utils.get_tile_building_entity_type(ct, current_pos)
                in CAN_DESTROY_TYPES
            ):
                bot.pending_build = (ActionType.CONVEYOR, current_pos, move_dir)


def execute(bot, ct: Controller):
    current_pos = ct.get_position()
    _update_return_target_while_tiling(bot, ct, current_pos)

    target_pos = (
        bot.return_target_pos if bot.return_target_pos is not None else bot.core_pos
    )
    target_kind = bot.return_target_kind

    if target_kind == TargetKind.CORE:
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
