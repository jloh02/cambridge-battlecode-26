import utils
import navigation
from cambc import Controller, EntityType, GameConstants, Position


TOP_PRIORITY_TYPES = {
    EntityType.CORE,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
}

EXCLUDED_HEAL_TYPES = {
    EntityType.ROAD,
    EntityType.MARKER,
}


def _priority_for_type(entity_type: EntityType) -> int | None:
    if entity_type in EXCLUDED_HEAL_TYPES:
        return None
    if entity_type in TOP_PRIORITY_TYPES:
        return 0
    return 1


def most_in_need_heal_candidate(bot, ct: Controller):
    """Return the best visible damaged friendly building candidate to heal.

    Priority order:
    1) core/conveyors/armoured conveyors
    2) other non-road friendly buildings
    Within each tier, pick the most missing HP, then nearest.
    """
    current_pos = ct.get_position()
    current_round = ct.get_current_round()
    my_team = ct.get_team()
    best = None
    best_key = None

    for x, y in getattr(bot, "visible_positions", set()):
        tile_data = bot.grid.get((x, y), {})
        if tile_data.get("last_seen") != current_round:
            continue

        building_type = tile_data.get("building")
        if building_type is None:
            continue
        if tile_data.get("building_team") != my_team:
            continue

        priority = _priority_for_type(building_type)
        if priority is None:
            continue

        pos = Position(x, y)
        building_id = tile_data.get("building_id")
        if building_id is None:
            continue

        hp = tile_data.get("building_hp")
        max_hp = tile_data.get("building_max_hp")
        if hp is None or max_hp is None:
            continue
        if hp >= max_hp:
            continue

        missing_hp = max_hp - hp
        dist_sq = current_pos.distance_squared(pos)
        candidate_key = (priority, -missing_hp, dist_sq, x, y)
        if best_key is not None and candidate_key >= best_key:
            continue

        best_key = candidate_key
        best = (building_type, pos, missing_hp, hp, max_hp)

    return best


def preemptive_heal_or_move(bot, ct: Controller) -> bool:
    """Heal the highest-need visible damaged friendly building, or move toward heal range."""
    current_pos = ct.get_position()
    best_candidate = most_in_need_heal_candidate(bot, ct)

    if best_candidate is None:
        return False

    entity_type, target_pos, missing_hp, hp, max_hp = best_candidate
    if ct.can_heal(target_pos):
        ct.heal(target_pos)
        bot.logger.log(
            f"Preemptive heal on {entity_type} at {target_pos} ({hp}/{max_hp}, missing {missing_hp})"
        )
        return True

    # Out of heal range: move toward the nearest tile that can heal this target.
    def is_heal_anchor(pos: Position) -> bool:
        return utils.is_position_passable_from_grid(
            bot,
            ct,
            pos,
            require_visible_this_round=True,
        )

    best_anchor = utils.closest_point_near_target(
        target_pos,
        current_pos,
        max_distance_sq=GameConstants.ACTION_RADIUS_SQ,
        include_target=False,
        is_valid=is_heal_anchor,
    )
    if best_anchor is None:
        return False

    if current_pos == best_anchor:
        return False

    moved = navigation.move_towards(bot, ct, best_anchor)
    if moved:
        bot.logger.log(
            f"Preemptive move to heal {entity_type} at {target_pos} via {best_anchor} ({hp}/{max_hp}, missing {missing_hp})"
        )
    return moved
