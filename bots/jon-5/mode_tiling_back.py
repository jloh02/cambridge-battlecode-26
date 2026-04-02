from cambc import Controller, EntityType, Position
from states import BuilderMode, TargetKind, ActionType
import utils
import navigation
import marker

CAN_DESTROY_TYPES = {EntityType.MARKER, EntityType.ROAD, None}


def _update_return_target_while_tiling(bot, ct: Controller, current_pos: Position):
    """Recalculates the closest drop-off point (core or friendly conveyor) as the bot moves."""
    core_target = utils.closest_point_on_grid(bot.core_pos, current_pos)
    best_target = core_target
    best_dist = utils.manhattan(current_pos, core_target)
    best_kind = TargetKind.CORE

    conveyor_candidates = [
        c for c in bot.connected_friendly_conveyors if c not in bot.tiled_back_positions
    ]
    if conveyor_candidates:
        nearest_c_tuple = min(
            conveyor_candidates,
            key=lambda c_pos: abs(current_pos.x - c_pos[0])
            + abs(current_pos.y - c_pos[1]),
        )
        nearest_c = Position(nearest_c_tuple[0], nearest_c_tuple[1])
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


def _is_at_core(
    bot, current_pos: Position, target_pos: Position, target_kind: str
) -> bool:
    """Checks if the bot has successfully tiled back to the core."""
    return (
        target_kind == TargetKind.CORE
        and utils.manhattan(current_pos, target_pos) == 0
        and not bot.pending_build
    )


def _check_connect_to_conveyor(
    bot, ct: Controller, current_pos: Position, target_pos: Position, target_kind: str
) -> bool:
    if target_kind != TargetKind.CONVEYOR or bot.pending_build:
        return False

    if utils.manhattan(current_pos, target_pos) == 0:
        return True

    # Allow connecting to an unwalkable conveyor/bridge from an adjacent tile
    if utils.manhattan(current_pos, target_pos) == 1:
        building_id = ct.get_tile_building_id(current_pos)
        if building_id is not None:
            et = ct.get_entity_type(building_id)
            if et in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}:
                if ct.get_direction(building_id) == utils.direction_toward(
                    current_pos, target_pos
                ):
                    return True

    return False


def _is_matching_bridge_present(
    ct: Controller, start_pos: Position, target_pos: Position
) -> bool:
    bridge_id = ct.get_tile_building_id(start_pos)
    if bridge_id is None or ct.get_entity_type(bridge_id) != EntityType.BRIDGE:
        return False

    bridge_target = ct.get_bridge_target(bridge_id)
    return bridge_target == target_pos


def _pos_tuple(pos: Position) -> tuple[int, int]:
    return (pos.x, pos.y)


def _execute_pending_build(bot, ct: Controller) -> bool:
    """Executes a queued build order if resources or obstacles previously prevented it."""
    if bot.pending_build is None:
        return False

    action_type = bot.pending_build[0]

    if action_type == ActionType.CONVEYOR:
        _, build_pos, build_dir = bot.pending_build
        if not ct.can_build_conveyor(build_pos, build_dir):
            _clear_obstacles_for_conveyor(bot, ct, build_pos, build_dir)
            bot.logger.log("can't execute pending conveyor build yet, maybe blocked?")
        if ct.can_build_conveyor(build_pos, build_dir):
            bot.logger.log(
                f"executing pending build of conveyor at {build_pos} toward {build_dir}"
            )
            ct.build_conveyor(build_pos, build_dir)
            bot.tiled_back_positions.add(_pos_tuple(build_pos))
            bot.pending_build = None
        return True

    elif action_type == ActionType.BRIDGE:
        _, start_pos, target_pos = bot.pending_build
        if _is_matching_bridge_present(ct, start_pos, target_pos):
            bot.logger.log(
                f"pending bridge from {start_pos} to {target_pos} is already built"
            )
            bot.tiled_back_positions.add(_pos_tuple(start_pos))
            bot.tiled_back_positions.add(_pos_tuple(target_pos))
            bot.pending_build = None
        elif ct.can_build_bridge(start_pos, target_pos):
            bot.logger.log(
                f"executing pending build of bridge from {start_pos} to {target_pos}"
            )
            ct.build_bridge(start_pos, target_pos)
            bot.tiled_back_positions.add(_pos_tuple(start_pos))
            bot.tiled_back_positions.add(_pos_tuple(target_pos))
            bot.pending_build = None
        else:
            _clear_obstacles_for_conveyor(bot, ct, start_pos, None)
            bot.logger.log("blocked from building pending bridge, waiting...")
        return True

    return False


def _clear_obstacles_for_conveyor(
    bot,
    ct: Controller,
    current_pos: Position,
    build_dir: Position,
    allow_destroy_conveyors: bool = True,
):
    """Destroys markers, roads, or misaligned conveyors to make way for the new path."""
    tile_team = bot.grid[_pos_tuple(current_pos)]["building_team"]
    enemy_team = tile_team is not None and tile_team != ct.get_team()
    # destroy enemy under us
    if enemy_team:
        if ct.can_fire(current_pos):
            ct.fire(current_pos)
            bot.logger.log(f"Fired on enemy building at {current_pos} to clear path")
        return

    et = bot.grid[_pos_tuple(current_pos)]["building"]
    if et in CAN_DESTROY_TYPES:
        if ct.can_destroy(current_pos):
            ct.destroy(current_pos)
            bot.logger.log(
                f"Destroyed {et} at {current_pos} to clear path for conveyor"
            )
        return

    if (
        allow_destroy_conveyors
        and et == EntityType.CONVEYOR
        and bot.grid[_pos_tuple(current_pos)]["building_dir"] != build_dir
    ):
        if ct.can_destroy(current_pos):
            ct.destroy(current_pos)
            bot.logger.log(
                f"Destroyed misaligned conveyor at {current_pos} to clear path"
            )
        return


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
            utils.destroy_marker_if_present(ct, next_pos)
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

    pending_bridge_plan = getattr(bot, "pending_bridge_plan", None)
    if pending_bridge_plan is not None:
        if ct.get_current_round() < getattr(bot, "bridge_transit_cooldown_until", -1):
            return

        bridge_start, jump_target_pos = pending_bridge_plan
        if current_pos != bridge_start:
            bot.pending_bridge_plan = None
        else:
            bot.stats["double_astar_turns"] += 1
            bot.bridge_transit_path = navigation.calculate_astar_path(
                bot,
                ct,
                start=current_pos,
                target=jump_target_pos,
                known_obstacles=bot.pathfinding_state["known_obstacles"],
                allow_bridges=False,
            )

            if bot.bridge_transit_path:
                bot.pending_bridge_plan = None
            else:
                bot.bridge_transit_cooldown_until = ct.get_current_round() + 2
            return

    # 1. Ask the brain what the plan is
    move_action, next_state = navigation.compute_pathfinding_step(
        bot,
        ct,
        current_pos,
        target_pos,
        current_state=bot.pathfinding_state,
        cardinal_only=True,
    )

    # Persist target/obstacle/path cache updates every turn.
    # We only consume a path step once an action is actually committed.
    bot.pathfinding_state = next_state

    if move_action is None:
        return

    action_type, action_val = move_action

    if action_type == ActionType.BRIDGE:
        jump_target_pos = action_val
        bot.logger.log(
            f"Master Path requires bridge from {current_pos} to {jump_target_pos}. Initiating transit."
        )

        # 1. Save the rest of the master route
        bot.saved_post_bridge_path = next_state["path"][1:]
        bot.pending_bridge_start = current_pos
        bot.pending_bridge_end = jump_target_pos
        bot.pending_bridge_plan = (current_pos, jump_target_pos)

    elif action_type == ActionType.CONVEYOR:
        move_dir = action_val
        next_action = next_state["path"][1] if len(next_state["path"]) > 1 else None

        # Build under ourselves
        if not ct.can_build_conveyor(current_pos, move_dir):
            _clear_obstacles_for_conveyor(bot, ct, current_pos, move_dir)
        if ct.can_build_conveyor(current_pos, move_dir):
            ct.build_conveyor(current_pos, move_dir)
            bot.tiled_back_positions.add(_pos_tuple(current_pos))
        else:
            current_cell = bot.grid[_pos_tuple(current_pos)]
            if (
                current_cell.get("building") != EntityType.CONVEYOR
                or current_cell.get("building_team") != ct.get_team()
                or current_cell.get("building_dir") != move_dir
            ):
                bot.pending_build = (ActionType.CONVEYOR, current_pos, move_dir)

        # Lookahead Building
        if next_action is not None:
            next_action_type, next_pos_best_dir = next_action
            next_pos = current_pos.add(move_dir)

            _clear_obstacles_for_conveyor(bot, ct, next_pos, next_pos_best_dir)
            if next_action_type == ActionType.CONVEYOR:
                if ct.can_build_conveyor(next_pos, next_pos_best_dir):
                    ct.build_conveyor(next_pos, next_pos_best_dir)
                    bot.tiled_back_positions.add(_pos_tuple(next_pos))
                # else:
                #     next_cell = bot.grid[_pos_tuple(next_pos)]
                #     if (
                #         next_cell.get("building") != EntityType.CONVEYOR
                #         or next_cell.get("building_team") != ct.get_team()
                #         or next_cell.get("building_dir") != next_pos_best_dir
                #     ):
                #         bot.pending_build = (
                #             ActionType.CONVEYOR,
                #             next_pos,
                #             next_pos_best_dir,
                #         )
            elif next_action_type == ActionType.BRIDGE:
                jump_target_pos = next_pos_best_dir
                # Note: If it builds ahead, it builds it BEFORE arriving. If this happens
                # frequently and traps you, you may want to remove this specific lookahead block.
                if ct.can_build_bridge(next_pos, jump_target_pos):
                    ct.build_bridge(next_pos, jump_target_pos)
                    bot.tiled_back_positions.add(_pos_tuple(next_pos))
                    next_state["known_obstacles"].discard((next_pos.x, next_pos.y))
                    # bot.pathfinding_state = next_state

        # Execute move
        if bot.pending_build is None and ct.can_move(move_dir):
            ct.move(move_dir)
            if bot.pathfinding_state["path"]:
                bot.pathfinding_state["path"].pop(0)


def _share_connected_conveyor_marker(bot, ct: Controller):
    if ct.get_position().distance_squared(bot.core_pos) > 2:
        return

    candidates = [
        pos_tuple
        for pos_tuple in bot.connected_friendly_conveyors
        if pos_tuple not in bot.shared_connected_conveyor_positions
    ]
    if not candidates:
        return

    best_tuple = max(
        candidates,
        key=lambda pos_tuple: abs(pos_tuple[0] - bot.core_pos.x)
        + abs(pos_tuple[1] - bot.core_pos.y),
    )
    marker_value = marker.create_connected_conveyor_marker(
        Position(best_tuple[0], best_tuple[1]),
        ct.get_current_round(),
        ct.get_map_width(),
        ct.get_map_height(),
    )
    if utils.place_marker_around(ct, ct.get_position(), marker_value):
        bot.shared_connected_conveyor_positions.add(best_tuple)
        bot.logger.log(f"Shared connected conveyor marker for {best_tuple}")


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
        _share_connected_conveyor_marker(bot, ct)
        bot.builder_mode = BuilderMode.FINDING_ORE
        return

    if _check_connect_to_conveyor(bot, ct, current_pos, target_pos, target_kind):
        _share_connected_conveyor_marker(bot, ct)
        bot.builder_mode = BuilderMode.FINDING_ORE
        return
