from cambc import Controller
from states import BuilderMode, ActionType, TargetKind
import utils
import navigation
import mode_exploring

MINIMUM_RESOURCE_TO_MINE_AXIONITE = 800
MINIMUM_AXIONITE_ROUND = 100


def _find_best_ore_target(bot, ct: Controller):
    """Finds the closest ore that isn't already claimed by a closer bot."""
    if not (bot.titanium_locations or bot.axionite_locations):
        return None

    can_target_ore = []
    for pos in utils.get_eligible_ore_locations(bot, ct):
        closest_pos = utils.closest_non_obstacle_cardinal_point_on_grid(
            bot, pos, ct.get_position()
        )
        if closest_pos is None:
            continue  # No valid adjacent position to target this ore
        d = ct.get_position().distance_squared(closest_pos)

        # Ensure no other friendly bot is closer
        if all(
            d
            <= bot_pos.distance_squared(
                utils.closest_non_obstacle_cardinal_point_on_grid(bot, pos, bot_pos)
            )
            for bot_pos in bot.bot_locations
            if utils.closest_non_obstacle_cardinal_point_on_grid(bot, pos, bot_pos)
            is not None
        ):
            can_target_ore.append((pos, closest_pos, d))

    if not can_target_ore:
        return None

    can_target_ore.sort(key=lambda x: x[1])
    return min(
        can_target_ore, key=lambda x: x[2]
    )  # Returns (pos, closest_pos, distance)


def _determine_return_target(bot, start_pos):
    """Calculates whether returning to the core or a nearby conveyor is more efficient."""
    visible_candidates = list(bot.known_friendly_conveyors)
    best_target = utils.closest_point_on_grid(bot.core_pos, start_pos)
    best_dist = utils.manhattan(start_pos, best_target)
    best_kind = TargetKind.CORE

    if visible_candidates:
        nearest_c = min(
            visible_candidates, key=lambda c_pos: utils.manhattan(start_pos, c_pos)
        )
        nearest_c_dist = utils.manhattan(start_pos, nearest_c)
        if nearest_c_dist < best_dist:
            best_target = nearest_c
            best_dist = nearest_c_dist
            best_kind = TargetKind.CONVEYOR

    bot.return_target_pos = best_target
    bot.return_target_dist_manhatten = best_dist
    bot.return_target_kind = best_kind


def _build_harvester_and_switch_mode(bot, ct: Controller, ore_pos):
    """Handles construction and state transition when ore is reached."""
    bot.logger.log(f"building harvester {ore_pos}")
    ct.build_harvester(ore_pos)

    bot.last_harvester_pos = ore_pos
    bot.tiled_back_positions = set()
    bot.nearest_conveyor_pos = None
    bot.nearest_conveyor_dist_manhatten = float("inf")

    # bot.bugnav_state = {"bugging": False, "side": 1, "start_dist": float("inf")}
    bot.pathfinding_state["path"] = []
    bot.explore_target_chunk = None
    bot.explore_target_pos = None

    bot.builder_mode = BuilderMode.TILING_BACK
    _determine_return_target(bot, ore_pos)


def execute(bot, ct: Controller):
    target_data = _find_best_ore_target(bot, ct)

    if target_data is not None:
        pos, closest_pos, _ = target_data

        # 1. Are we adjacent to the ore? Build Harvester.
        if utils.manhattan(pos, ct.get_position()) == 1:
            if ct.can_build_harvester(pos):
                _build_harvester_and_switch_mode(bot, ct, pos)
            else:
                bot.logger.log(
                    f"standing on ore at {pos}, trying to build harvester, {ct.get_global_resources()}/{ct.get_harvester_cost()}"
                )
            return

        # 2. Check resources before committing to movement.
        if (
            ct.get_global_resources()[0] < ct.get_harvester_cost()[0]
            or ct.get_global_resources()[0] < ct.get_conveyor_cost()[0]
        ):
            utils.move_random(ct)  # random move to prevent blocking
            bot.logger.log(
                f"don't find more ores when resources are low: {ct.get_global_resources()[0]}"
            )
            return

        # 3. Move toward the ore.
        bot.logger.log(f"moving towards ore at {pos}, closest: {closest_pos}")
        navigation.move_towards(bot, ct, closest_pos)
        return

    # Fallback if no target is found
    bot.builder_mode = BuilderMode.EXPLORING
    mode_exploring.execute(bot, ct)
