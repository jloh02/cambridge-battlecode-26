from __future__ import annotations

from cambc import Controller, Direction, EntityType, Environment, Position

import assault
import navigation
import utils
from bots.orange_v1.policy.enemy_base import scout_target_for_direction


ASSAULT_OBJECTIVE_TTL = 16
ASSAULT_SPAWN_DIRECTIONS = (
    Direction.NORTHEAST,
    Direction.NORTHWEST,
    Direction.SOUTHEAST,
    Direction.SOUTHWEST,
)
ASSAULT_SYMMETRY_BY_SLOT = ("ROT180", "MIRROR_X", "MIRROR_Y", "ROT180")
ASSAULT_ANCHOR_OFFSET_BY_SLOT = {
    0: Direction.NORTH,
    1: Direction.WEST,
    2: Direction.EAST,
    3: Direction.SOUTH,
}
PASSABLE_ASSAULT_BUILDINGS = {
    None,
    EntityType.ROAD,
    EntityType.MARKER,
}


def _predict_enemy_anchor(bot, ct: Controller) -> Position | None:
    if bot.core_pos is None or bot.assault_slot is None:
        return None
    max_x = ct.get_map_width() - 1
    max_y = ct.get_map_height() - 1
    mode = ASSAULT_SYMMETRY_BY_SLOT[bot.assault_slot]
    if mode == "ROT180":
        anchor = Position(max_x - bot.core_pos.x, max_y - bot.core_pos.y)
    elif mode == "MIRROR_X":
        anchor = Position(max_x - bot.core_pos.x, bot.core_pos.y)
    else:
        anchor = Position(bot.core_pos.x, max_y - bot.core_pos.y)
    offset_dir = ASSAULT_ANCHOR_OFFSET_BY_SLOT[bot.assault_slot]
    candidate = anchor.add(offset_dir)
    if utils.in_bounds(ct, candidate):
        return candidate
    return anchor


def _legal_fire_fn(ct: Controller):
    if not hasattr(ct, "can_fire_from"):
        return None

    def _legal(position: Position, direction: Direction, target: Position) -> bool:
        try:
            return ct.can_fire_from(position, direction, EntityType.SENTINEL, target)
        except Exception:
            return False

    return _legal


def _blocked_ring_positions(bot, ct: Controller) -> set[Position]:
    blocked: set[Position] = set()
    for pos_tuple in getattr(bot, "visible_positions", set()):
        data = bot.grid.get(pos_tuple, {})
        if data.get("building") == EntityType.SENTINEL and data.get("building_team") == ct.get_team():
            blocked.add(Position(pos_tuple[0], pos_tuple[1]))
    return blocked


def _is_clearable_enemy_conveyor(bot, ct: Controller, position: Position) -> bool:
    data = bot.grid.get((position.x, position.y), {})
    return (
        data.get("building") in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}
        and data.get("building_team") is not None
        and data.get("building_team") != ct.get_team()
    )


def _tile_is_usable_ring_site(bot, ct: Controller, position: Position) -> bool:
    data = bot.grid.get((position.x, position.y))
    if data is None:
        return False
    if data.get("env") != Environment.EMPTY:
        return False
    if data.get("entity") == EntityType.BUILDER_BOT and data.get("id") != ct.get_id():
        return False
    building = data.get("building")
    if building in PASSABLE_ASSAULT_BUILDINGS:
        return True
    return _is_clearable_enemy_conveyor(bot, ct, position)


def _visible_friendly_ring_sentinels(bot, ct: Controller, anchor: Position) -> set[Position]:
    positions: set[Position] = set()
    for direction in assault.CARDINAL_DIRECTIONS:
        ring_position = anchor.add(direction)
        data = bot.grid.get((ring_position.x, ring_position.y), {})
        if (
            data.get("building") == EntityType.SENTINEL
            and data.get("building_team") == ct.get_team()
        ):
            positions.add(ring_position)
    return positions


def _assault_enemies(bot) -> list[assault.VisibleEnemy]:
    return list(getattr(bot, "visible_enemy_targets", []))


def _ring_sentinel_count(bot, ct: Controller, anchor: Position) -> int:
    return len(_visible_friendly_ring_sentinels(bot, ct, anchor))


def _best_visible_site(bot, ct: Controller) -> assault.AssaultSite | None:
    enemies = _assault_enemies(bot)
    if not enemies:
        return None
    raw_site = assault.choose_best_assault_site(
        current_position=ct.get_position(),
        enemies=enemies,
        map_width=ct.get_map_width(),
        map_height=ct.get_map_height(),
        blocked_ring_positions=_blocked_ring_positions(bot, ct),
        legal_fire_fn=_legal_fire_fn(ct),
    )
    if raw_site is None:
        return None
    if not _tile_is_usable_ring_site(bot, ct, raw_site.ring_position):
        return None
    return raw_site


def _best_site_for_anchor(bot, ct: Controller, anchor: Position) -> assault.AssaultSite | None:
    enemies = _assault_enemies(bot)
    if not enemies:
        return None
    raw_site = assault.choose_best_site_for_harvester(
        harvester_position=anchor,
        current_position=ct.get_position(),
        enemies=enemies,
        map_width=ct.get_map_width(),
        map_height=ct.get_map_height(),
        blocked_ring_positions=_blocked_ring_positions(bot, ct) | _visible_friendly_ring_sentinels(bot, ct, anchor),
        legal_fire_fn=_legal_fire_fn(ct),
    )
    if raw_site is None:
        return None
    if not _tile_is_usable_ring_site(bot, ct, raw_site.ring_position):
        return None
    return raw_site


def _best_sidestep(bot, ct: Controller, blocked_position: Position, anchor: Position) -> Position | None:
    candidates = []
    for direction in utils.DIRECTIONS:
        candidate = blocked_position.add(direction)
        if not utils.in_bounds(ct, candidate):
            continue
        if candidate == anchor:
            continue
        if not utils.is_passable(bot, ct, blocked_position, direction):
            continue
        data = bot.grid.get((candidate.x, candidate.y), {})
        if data.get("entity") == EntityType.BUILDER_BOT and data.get("entity_team") == ct.get_team():
            continue
        candidates.append(candidate)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda candidate: (
            assault.manhattan(candidate, anchor),
            candidate.x,
            candidate.y,
        ),
    )


def _move_toward(bot, ct: Controller, target: Position) -> None:
    bot.logger.log(f"assault moving toward {target}")
    if navigation.move_towards(bot, ct, target):
        return
    utils.move_random(ct)


def _execute_site(bot, ct: Controller, site: assault.AssaultSite) -> bool:
    bot.assault_anchor_position = site.harvester_position
    bot.assault_anchor_last_seen_round = ct.get_current_round()
    current_pos = ct.get_position()
    ring_position = site.ring_position

    if current_pos == ring_position:
        if _is_clearable_enemy_conveyor(bot, ct, ring_position):
            if ct.can_fire(current_pos):
                ct.fire(current_pos)
            return True
        sidestep = _best_sidestep(bot, ct, ring_position, site.harvester_position)
        if sidestep is not None:
            move_dir = current_pos.direction_to(sidestep)
            if ct.can_move(move_dir):
                ct.move(move_dir)
                return True
        return False

    if max(abs(current_pos.x - ring_position.x), abs(current_pos.y - ring_position.y)) <= 1:
        if _is_clearable_enemy_conveyor(bot, ct, ring_position):
            _move_toward(bot, ct, ring_position)
            return True
        if ct.can_build_sentinel(ring_position, site.sentinel_direction):
            ct.build_sentinel(ring_position, site.sentinel_direction)
            return True

    _move_toward(bot, ct, ring_position)
    return True


def _refresh_anchor_objective(bot, ct: Controller) -> bool:
    anchor = bot.assault_anchor_position
    if anchor is None:
        return False
    if ct.get_current_round() - bot.assault_anchor_last_seen_round > ASSAULT_OBJECTIVE_TTL:
        bot.assault_anchor_position = None
        return False
    site = _best_site_for_anchor(bot, ct, anchor)
    if site is not None:
        return _execute_site(bot, ct, site)
    _move_toward(bot, ct, anchor)
    return True


def _scout(bot, ct: Controller) -> None:
    anchor = bot.last_enemy_core_position or _predict_enemy_anchor(bot, ct)
    if anchor is None:
        return
    scout_direction = ASSAULT_SPAWN_DIRECTIONS[bot.assault_slot]
    target = scout_target_for_direction(
        anchor,
        map_width=ct.get_map_width(),
        map_height=ct.get_map_height(),
        direction=scout_direction,
    )
    _move_toward(bot, ct, target)


def execute(bot, ct: Controller):
    if bot.assault_anchor_position is not None and _ring_sentinel_count(bot, ct, bot.assault_anchor_position) > 0:
        site = _best_site_for_anchor(bot, ct, bot.assault_anchor_position)
        if site is not None:
            _execute_site(bot, ct, site)
            return
    site = _best_visible_site(bot, ct)
    if site is not None:
        _execute_site(bot, ct, site)
        return
    if _refresh_anchor_objective(bot, ct):
        return
    _scout(bot, ct)
