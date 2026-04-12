from cambc import Controller, EntityType, Position
from states import BuilderMode, TargetKind, ActionType
import utils
import navigation
import marker
import timing

CAN_DESTROY_TYPES = {EntityType.MARKER, EntityType.ROAD, None}
# Subset of CAN_DESTROY_TYPES that actually needs a pre-build destroy step.
# Markers have to be removed before a conveyor can be placed, but roads are
# subsumed by the conveyor build on the same tile, so destroying the road
# first is pure wasted action cooldown.
_CLEAR_FOR_CONVEYOR_DESTROY_TYPES = {EntityType.MARKER}
PIPELINE_BUILDINGS = {
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
}
RETURN_TARGET_REFRESH_INTERVAL = 4
RETURN_TARGET_HYSTERESIS = 3
ENABLE_CONNECTED_HARVESTER_MARKERS = False
CORE_PORT_SPREAD_MAX_EXTRA_DIST = 4
PENDING_BUILD_STALL_LIMIT = 6
PENDING_BUILD_TEMP_OBSTACLE_TTL = 8
DIRECT_CORE_FALLBACK_STALL_LIMIT = 12
NAV_STALL_LIMIT = 40
NAV_STALL_BLACKLIST_BASE_TTL = 60
NAV_STALL_BLACKLIST_ESCALATION = 120
NAV_STALL_BLACKLIST_PERMANENT_AFTER = 3
PIPELINE_CLAIM_MARKER_INTERVAL = 10
PIPELINE_CLAIM_MAX_PER_BUILDER = 8
PIPELINE_CLAIM_PATH_RESERVE_STEPS = 6
ENABLE_PIPELINE_CLAIM_MARKERS = False
# Enabled: each builder locks onto ONE core approach slot (one of the 12
# cardinal tiles ringing the 3x3 core footprint) and targets it directly
# instead of aiming at a core cell and relying on A* best-effort. This
# stops the "lots of occupied approach slots but only 4 carry flow"
# pattern the replay graph analysis flagged — individual builders no
# longer race each other for the same slot and orphan leftover conveyor
# stubs when A* re-targets mid-route.
ENABLE_CORE_LANE_SLOT_TARGETING = True


def _nearest_connected_conveyor(bot, current_pos: Position):
    """Same strategy as `jon-5`, cheaper execution: scan the lane set only when needed."""
    best_target = None
    best_dist = float("inf")
    best_score = float("inf")

    for c_pos, harvester_count in bot.connected_friendly_conveyors.items():
        if c_pos in bot.tiled_back_positions:
            continue

        candidate_dist = abs(current_pos.x - c_pos[0]) + abs(current_pos.y - c_pos[1])
        candidate_score = candidate_dist + navigation.connected_conveyor_load_penalty(
            harvester_count
        )
        if candidate_score > best_score:
            continue
        if candidate_score == best_score and candidate_dist >= best_dist:
            continue

        best_target = Position(c_pos[0], c_pos[1])
        best_dist = candidate_dist
        best_score = candidate_score

    return best_target, best_dist, best_score


def _core_tile_candidates(bot, ct: Controller) -> list[Position]:
    core_pos = bot.core_pos
    if core_pos is None:
        return []
    map_w = ct.get_map_width()
    map_h = ct.get_map_height()
    candidates = []
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            pos = Position(core_pos.x + dx, core_pos.y + dy)
            if 0 <= pos.x < map_w and 0 <= pos.y < map_h:
                candidates.append(pos)
    return candidates


def _core_approach_slots(bot, ct: Controller) -> list[Position]:
    """Return the 12 cardinal approach slots around the 3x3 core footprint."""
    core_pos = bot.core_pos
    if core_pos is None:
        return []
    map_w = ct.get_map_width()
    map_h = ct.get_map_height()
    candidates = []
    for dx in range(-1, 2):
        for y in (core_pos.y - 2, core_pos.y + 2):
            if 0 <= core_pos.x + dx < map_w and 0 <= y < map_h:
                candidates.append(Position(core_pos.x + dx, y))
    for dy in range(-1, 2):
        for x in (core_pos.x - 2, core_pos.x + 2):
            if 0 <= x < map_w and 0 <= core_pos.y + dy < map_h:
                candidates.append(Position(x, core_pos.y + dy))
    return candidates


def _core_tile_for_approach_slot(bot, slot: Position) -> Position | None:
    core_pos = bot.core_pos
    if core_pos is None:
        return None
    core_x = min(max(slot.x, core_pos.x - 1), core_pos.x + 1)
    core_y = min(max(slot.y, core_pos.y - 1), core_pos.y + 1)
    return Position(core_x, core_y)


def _is_core_approach_slot(bot, pos: Position | None) -> bool:
    if pos is None or bot.core_pos is None:
        return False
    dx = abs(pos.x - bot.core_pos.x)
    dy = abs(pos.y - bot.core_pos.y)
    return max(dx, dy) == 2 and min(dx, dy) <= 1


def _clear_core_return_state(bot) -> None:
    bot.tiling_force_core_return = False
    bot.tiling_prefer_core_return = False
    bot.tiling_core_approach_full = False
    bot.core_return_target_pos = None
    bot.core_lane_slot_pos = None
    bot.core_lane_core_tile_pos = None
    bot.core_lane_exit_built = False


def _assign_core_lane_slot(bot, ct: Controller, origin: Position) -> Position | None:
    cached_slot = getattr(bot, "core_lane_slot_pos", None)
    if _is_core_approach_slot(bot, cached_slot):
        return cached_slot

    slots = _core_approach_slots(bot, ct)
    if not slots:
        return None

    spawn_pos = getattr(bot, "spawn_pos", None)
    harvester_pos = getattr(bot, "last_harvester_pos", None)
    owner_id = ct.get_id() if hasattr(ct, "get_id") else 0
    seed_pos = harvester_pos or spawn_pos or origin
    lane_hash = (
        (seed_pos.x * 83492791)
        ^ (seed_pos.y * 2654435761)
        ^ (owner_id * 97531)
    ) & 0xFFFFFFFF
    my_team = ct.get_team() if hasattr(ct, "get_team") else None
    grid = getattr(bot, "grid", {})
    eligible = []
    fallback = []
    connected = getattr(bot, "connected_friendly_conveyors", {})
    for slot in slots:
        slot_key = _pos_tuple(slot)
        tile_data = grid.get(slot_key)
        if tile_data is None:
            env = None
            building = None
            building_team = None
        else:
            env = tile_data.get("env")
            building = tile_data.get("building")
            building_team = tile_data.get("building_team")
        if env in navigation.IMPASSABLE_TILES:
            continue
        if building is not None:
            if (
                building in PIPELINE_BUILDINGS
                and building_team == my_team
                and slot_key in getattr(bot, "claimed_pipeline_positions", set())
            ):
                continue
            if building not in CAN_DESTROY_TYPES:
                continue
        # Orphan-aware slot scoring: prefer slots that are EITHER
        #   * Already a connected friendly conveyor feeding the core
        #     (verified working delivery path), OR
        #   * Empty / road / marker (we will build a fresh chain into
        #     them).
        # Actively deprioritise slots that have a friendly transport
        # building but are NOT in connected_friendly_conveyors — those
        # are orphan stubs from previous builders whose chain broke,
        # and committing another builder to them just produces another
        # orphan instead of useful flow.
        is_friendly_transport = (
            building in PIPELINE_BUILDINGS and building_team == my_team
        )
        is_connected = is_friendly_transport and slot_key in connected
        if is_friendly_transport and not is_connected:
            orphan_penalty = 100
        else:
            orphan_penalty = 0
        slot_score = utils.manhattan(origin, slot) + orphan_penalty
        tie = lane_hash ^ (slot.x * 73856093) ^ (slot.y * 19349663)
        eligible.append((slot_score, tie & 0xFFFF, slot))
        fallback.append((tie & 0xFFFF, slot))

    if eligible:
        eligible.sort()
        slot = eligible[0][2]
    elif fallback:
        fallback.sort()
        slot = fallback[0][1]
    else:
        slot = slots[lane_hash % len(slots)]
    bot.core_lane_slot_pos = slot
    bot.core_lane_core_tile_pos = _core_tile_for_approach_slot(bot, slot)
    if getattr(bot, "logger", None) is not None:
        bot.logger.log(
            f"assigned core lane slot {slot} toward {bot.core_lane_core_tile_pos}"
        )
    return slot


def _core_approach_ring_visibly_full(bot, ct: Controller) -> bool:
    slots = _core_approach_slots(bot, ct)
    if not slots:
        return False

    is_in_vision = getattr(ct, "is_in_vision", None)
    for slot in slots:
        if is_in_vision is not None and not is_in_vision(slot):
            return False
        tile_data = bot.grid.get(_pos_tuple(slot))
        if tile_data is None:
            return False
        if tile_data.get("env") in navigation.IMPASSABLE_TILES:
            continue
        building = tile_data.get("building")
        if building in CAN_DESTROY_TYPES:
            return False
    return True


def _is_valid_cached_core_target(bot, ct: Controller, target_pos: Position | None) -> bool:
    if target_pos is None or bot.core_pos is None:
        return False
    if target_pos == getattr(bot, "core_lane_slot_pos", None):
        return _is_core_approach_slot(bot, target_pos)
    if max(abs(target_pos.x - bot.core_pos.x), abs(target_pos.y - bot.core_pos.y)) > 1:
        return False
    return 0 <= target_pos.x < ct.get_map_width() and 0 <= target_pos.y < ct.get_map_height()


def _fallback_direct_core_to_pipeline(bot, reason: str) -> bool:
    if not getattr(bot, "tiling_prefer_core_return", False):
        return False
    if getattr(bot, "tiling_force_core_return", False):
        return False

    bot.logger.log(f"direct core route fallback: {reason}; allowing pipeline merge")
    _clear_core_return_state(bot)
    bot.nearest_conveyor_pos = None
    bot.nearest_conveyor_dist_manhatten = float("inf")
    bot.return_target_pos = None
    bot.return_target_dist_manhatten = float("inf")
    bot.return_target_kind = TargetKind.CORE
    bot.pending_build = None
    bot.pending_bridge_plan = None
    bot.bridge_transit_path = None
    bot.bridge_transit_cooldown_until = -1
    state = bot.pathfinding_state
    state["path"] = []
    state["planner_state"] = None
    state["last_replan_signature"] = None
    state.pop("tiling_back_nav_stall_turns", None)
    state.pop("tiling_back_nav_stall_pos", None)
    state.pop("tiling_back_pos_history", None)
    state.pop("tiling_back_osc_count", None)
    state.pop("pending_build_stall_turns", None)
    state.pop("pending_build_stall_pos", None)
    return True


def _select_core_return_target(bot, ct: Controller, current_pos: Position) -> Position:
    default_target = utils.closest_point_on_grid(bot.core_pos, current_pos)
    if not (
        getattr(bot, "tiling_force_core_return", False)
        or getattr(bot, "tiling_prefer_core_return", False)
    ):
        bot.core_return_target_pos = None
        bot.core_lane_slot_pos = None
        bot.core_lane_core_tile_pos = None
        bot.core_lane_exit_built = False
        return default_target

    if ENABLE_CORE_LANE_SLOT_TARGETING:
        lane_slot = _assign_core_lane_slot(bot, ct, origin=current_pos)
        lane_core_tile = getattr(bot, "core_lane_core_tile_pos", None)
        if lane_slot is not None and lane_core_tile is not None:
            bot.core_return_target_pos = lane_core_tile
            return lane_core_tile

    cached_core_target = getattr(bot, "core_return_target_pos", None)
    if _is_valid_cached_core_target(bot, ct, cached_core_target):
        return cached_core_target

    candidates = _core_tile_candidates(bot, ct)
    if not candidates:
        return default_target

    default_dist = utils.manhattan(current_pos, default_target)
    origin = (
        getattr(bot, "last_harvester_pos", None)
        or getattr(bot, "spawn_pos", None)
        or current_pos
    )

    eligible = []
    for candidate in candidates:
        dist = utils.manhattan(current_pos, candidate)
        if dist > default_dist + CORE_PORT_SPREAD_MAX_EXTRA_DIST:
            continue
        eligible.append((dist, candidate.x, candidate.y, candidate))

    if not eligible:
        bot.core_return_target_pos = default_target
        return default_target

    eligible.sort()
    hash_value = (
        (origin.x * 83492791)
        ^ (origin.y * 2654435761)
        ^ (current_pos.x * 73856093)
        ^ (current_pos.y * 19349663)
    ) & 0xFFFF
    best_target = eligible[hash_value % len(eligible)][3]

    bot.core_return_target_pos = best_target
    return best_target


def _cached_conveyor_target_is_valid(bot) -> bool:
    conveyor_pos = bot.nearest_conveyor_pos
    if conveyor_pos is None:
        return False

    conveyor_key = (conveyor_pos.x, conveyor_pos.y)
    if conveyor_key in bot.tiled_back_positions:
        return False

    return conveyor_key in bot.connected_friendly_conveyors


def _update_return_target_while_tiling(bot, ct: Controller, current_pos: Position):
    """Recalculates the closest drop-off point (core or friendly conveyor) as the bot moves."""
    round_now = ct.get_current_round()
    core_target = _select_core_return_target(bot, ct, current_pos)
    best_target = core_target
    best_dist = utils.manhattan(current_pos, core_target)
    best_score = best_dist
    best_kind = TargetKind.CORE

    refresh_due = (
        round_now - bot.last_return_target_refresh_round
        >= RETURN_TARGET_REFRESH_INTERVAL
    )
    topology_changed = (
        bot.last_connected_refresh_round > bot.last_return_target_refresh_round
    )
    cached_conveyor_valid = _cached_conveyor_target_is_valid(bot)
    should_refresh_conveyor = (
        bot.last_return_target_refresh_round < 0
        or topology_changed
        or refresh_due
        # Same strategy as `jon-5`, cheaper execution: keep exact per-turn
        # conveyor retargeting while a conveyor is actively winning, because
        # that choice feeds directly into the lane-construction route.
        or bot.return_target_kind == TargetKind.CONVEYOR
    )

    core_approach_full = _core_approach_ring_visibly_full(bot, ct)
    bot.tiling_core_approach_full = core_approach_full
    prefer_direct_core = (
        getattr(bot, "tiling_force_core_return", False)
        or (
            getattr(bot, "tiling_prefer_core_return", False)
            and not core_approach_full
        )
    )
    force_conveyor_merge = (
        getattr(bot, "tiling_prefer_core_return", False)
        and not getattr(bot, "tiling_force_core_return", False)
        and core_approach_full
    )

    if prefer_direct_core:
        conveyor_target = None
        conveyor_dist = float("inf")
        conveyor_score = float("inf")
    elif should_refresh_conveyor:
        conveyor_target, conveyor_dist, conveyor_score = _nearest_connected_conveyor(
            bot, current_pos
        )
        bot.nearest_conveyor_pos = conveyor_target
        bot.nearest_conveyor_dist_manhatten = conveyor_dist
        bot.last_return_target_refresh_round = round_now
    elif cached_conveyor_valid and bot.nearest_conveyor_pos is not None:
        conveyor_target = bot.nearest_conveyor_pos
        conveyor_dist = abs(current_pos.x - conveyor_target.x) + abs(
            current_pos.y - conveyor_target.y
        )
        conveyor_score = conveyor_dist + navigation.connected_conveyor_load_penalty(
            bot.connected_friendly_conveyors.get(
                (conveyor_target.x, conveyor_target.y), 0
            )
        )
        bot.nearest_conveyor_dist_manhatten = conveyor_dist
    else:
        conveyor_target = None
        conveyor_dist = float("inf")
        conveyor_score = float("inf")

    if conveyor_target is not None and (force_conveyor_merge or conveyor_score < best_score):
        best_target = conveyor_target
        best_dist = conveyor_dist
        best_score = conveyor_score
        best_kind = TargetKind.CONVEYOR

    bot.return_target_pos = best_target
    bot.return_target_dist_manhatten = best_dist
    bot.return_target_kind = best_kind
    # Keep the cached nearest conveyor separate from the currently selected
    # return target. Forgetting it whenever the core is temporarily better makes
    # the next turn pay the full scan again and weakens the intended amortization.
    bot.nearest_conveyor_pos = conveyor_target
    bot.nearest_conveyor_dist_manhatten = conveyor_dist


def _is_at_core(
    bot, ct: Controller, current_pos: Position, target_pos: Position, target_kind: str
) -> bool:
    """Checks if the bot has successfully tiled back to the core."""
    if target_kind != TargetKind.CORE or bot.pending_build:
        return False
    lane_slot = getattr(bot, "core_lane_slot_pos", None)
    if lane_slot is not None and target_pos == lane_slot:
        core_tile = getattr(bot, "core_lane_core_tile_pos", None)
        if current_pos != lane_slot:
            return False
        if core_tile is None:
            return True
        return (
            getattr(bot, "core_lane_exit_built", False)
            or _visible_matching_friendly_conveyor(
                bot,
                ct,
                lane_slot,
                utils.direction_toward(lane_slot, core_tile),
            )
        )
    return (
        utils.manhattan(current_pos, target_pos) == 0
    )


def _ensure_core_slot_exit(
    bot,
    ct: Controller,
    current_pos: Position,
    target_pos: Position,
    target_kind: str,
) -> bool:
    lane_slot = getattr(bot, "core_lane_slot_pos", None)
    core_tile = getattr(bot, "core_lane_core_tile_pos", None)
    if (
        target_kind != TargetKind.CORE
        or lane_slot is None
        or core_tile is None
        or target_pos != lane_slot
        or current_pos != lane_slot
        or bot.pending_build is not None
    ):
        return False

    final_dir = utils.direction_toward(lane_slot, core_tile)
    if _visible_matching_friendly_conveyor(bot, ct, lane_slot, final_dir):
        bot.core_lane_exit_built = True
        return False
    if _visible_protected_pipeline_at(bot, ct, lane_slot):
        _protect_pipeline_temp_obstacle(
            bot,
            ct,
            lane_slot,
            "core lane slot already contains protected transport",
        )
        return True
    if ct.can_build_conveyor(lane_slot, final_dir):
        ct.build_conveyor(lane_slot, final_dir)
        _record_built_pipeline_tile(
            bot,
            ct,
            lane_slot,
            final_dir,
            reserved_keys={_pos_tuple(lane_slot)},
        )
        bot.core_lane_exit_built = True
        return False
    _clear_obstacles_for_conveyor(bot, ct, lane_slot, final_dir)
    if not ct.can_build_conveyor(lane_slot, final_dir):
        bot.pending_build = (ActionType.CONVEYOR, lane_slot, final_dir)
    return True


def _check_connect_to_conveyor(
    bot, ct: Controller, current_pos: Position, target_pos: Position, target_kind: str
) -> bool:
    if target_kind != TargetKind.CONVEYOR or bot.pending_build:
        return False

    if utils.manhattan(current_pos, target_pos) == 0:
        current_key = _pos_tuple(current_pos)
        tile_data = bot.grid.get(current_key)
        if tile_data is None:
            return False
        building = tile_data.get("building")
        return (
            current_key in bot.connected_friendly_conveyors
            and tile_data.get("building_team") == ct.get_team()
            and building in PIPELINE_BUILDINGS
        )

    # Allow connecting to an unwalkable conveyor/bridge from an adjacent tile
    if utils.manhattan(current_pos, target_pos) == 1:
        building_id = ct.get_tile_building_id(current_pos)
        if building_id is not None:
            et = ct.get_entity_type(building_id)
            if et in {EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.ARMOURED_CONVEYOR}:
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


def _visible_friendly_pipeline_at(bot, ct: Controller, pos: Position) -> bool:
    tile_data = bot.grid.get(_pos_tuple(pos))
    if tile_data is None:
        return False
    return (
        tile_data.get("building") in PIPELINE_BUILDINGS
        and tile_data.get("building_team") == ct.get_team()
    )


def _visible_protected_pipeline_at(bot, ct: Controller, pos: Position) -> bool:
    if not _visible_friendly_pipeline_at(bot, ct, pos):
        return False
    pos_key = _pos_tuple(pos)
    if (
        pos_key in getattr(bot, "connected_friendly_conveyors", {})
        or pos_key in getattr(bot, "claimed_pipeline_positions", set())
    ):
        return True
    return pos_key not in getattr(bot, "tiled_back_positions", set())


def _should_record_friendly_pipeline_progress(bot, pos: Position) -> bool:
    pos_key = _pos_tuple(pos)
    return (
        pos_key in getattr(bot, "connected_friendly_conveyors", {})
        or pos_key in getattr(bot, "claimed_pipeline_positions", set())
        or pos_key in getattr(bot, "tiled_back_positions", set())
    )


_MATCHING_CONVEYOR_TYPES = frozenset(
    {
        EntityType.CONVEYOR,
        EntityType.SPLITTER,
        EntityType.ARMOURED_CONVEYOR,
    }
)


def _visible_matching_friendly_conveyor(
    bot,
    ct: Controller,
    pos: Position,
    build_dir,
) -> bool:
    """Does the visible tile already hold a friendly directional transport
    building (conveyor / splitter / armoured conveyor) pointing the way we
    want to build? If yes, we do not need to lay another conveyor over it —
    it is already carrying resources in the right direction."""
    tile_data = bot.grid.get(_pos_tuple(pos))
    if tile_data is None:
        return False
    return (
        tile_data.get("building") in _MATCHING_CONVEYOR_TYPES
        and tile_data.get("building_team") == ct.get_team()
        and tile_data.get("building_dir") == build_dir
    )


def _protect_pipeline_temp_obstacle(bot, ct: Controller, pos: Position, reason: str):
    bot.pathfinding_state.setdefault("temporary_obstacles", {})[_pos_tuple(pos)] = (
        ct.get_current_round() + PENDING_BUILD_TEMP_OBSTACLE_TTL
    )
    bot.pathfinding_state["path"] = []
    bot.pathfinding_state["planner_state"] = None
    bot.pathfinding_state["last_replan_signature"] = None
    bot.logger.log(f"preserving friendly pipeline at {pos}; {reason}")


def _future_path_keys(start_pos: Position, path, limit: int = PIPELINE_CLAIM_PATH_RESERVE_STEPS):
    reserved = {_pos_tuple(start_pos)}
    cursor = start_pos
    for action_type, action_val in list(path or [])[:limit]:
        if action_type == ActionType.CONVEYOR:
            cursor = cursor.add(action_val)
            reserved.add(_pos_tuple(cursor))
        elif action_type == ActionType.BRIDGE:
            cursor = action_val
            reserved.add(_pos_tuple(cursor))
    return reserved


def _claim_marker_directions(build_dir):
    if build_dir is None:
        return utils.DIRECTIONS
    bdx, bdy = build_dir.delta()

    def score(direction):
        dx, dy = direction.delta()
        dot = abs(dx * bdx + dy * bdy)
        cardinal_penalty = 0 if abs(dx) + abs(dy) == 1 else 1
        return (dot, cardinal_penalty)

    return sorted(utils.DIRECTIONS, key=score)


def _is_safe_pipeline_claim_marker_tile(
    bot,
    ct: Controller,
    marker_pos: Position,
    claimed_pos: Position,
    reserved_keys,
) -> bool:
    marker_key = _pos_tuple(marker_pos)
    if not (0 <= marker_pos.x < ct.get_map_width() and 0 <= marker_pos.y < ct.get_map_height()):
        return False
    if marker_key == _pos_tuple(claimed_pos) or marker_key in reserved_keys:
        return False
    if bot.core_pos is not None and max(
        abs(marker_pos.x - bot.core_pos.x),
        abs(marker_pos.y - bot.core_pos.y),
    ) <= 2:
        return False

    tile_data = bot.grid.get(marker_key)
    if tile_data is not None:
        if tile_data.get("env") in utils.DO_NOT_BUILD_ON:
            return False
        if tile_data.get("building") is not None or tile_data.get("entity") is not None:
            return False
    if marker_key in getattr(bot, "known_friendly_conveyors", set()):
        return False
    if marker_key in getattr(bot, "connected_friendly_conveyors", {}):
        return False
    if marker_key in getattr(bot, "claimed_pipeline_positions", set()):
        return False
    if Position(marker_pos.x, marker_pos.y) in getattr(bot, "titanium_locations", set()):
        return False
    if Position(marker_pos.x, marker_pos.y) in getattr(bot, "axionite_locations", set()):
        return False
    return ct.can_place_marker(marker_pos)


def _try_share_pipeline_claim_marker(
    bot,
    ct: Controller,
    claimed_pos: Position,
    build_dir,
    *,
    reserved_keys=None,
) -> bool:
    claimed_key = _pos_tuple(claimed_pos)
    if not hasattr(ct, "can_place_marker") or not hasattr(ct, "place_marker"):
        return False
    if claimed_key in getattr(bot, "connected_friendly_conveyors", {}):
        return False
    shared = getattr(bot, "shared_pipeline_claim_positions", None)
    if shared is None:
        shared = set()
        bot.shared_pipeline_claim_positions = shared
    if claimed_key in shared or len(shared) >= PIPELINE_CLAIM_MAX_PER_BUILDER:
        return False

    current_round = ct.get_current_round()
    if current_round - getattr(bot, "last_pipeline_claim_round", -9999) < PIPELINE_CLAIM_MARKER_INTERVAL:
        return False
    if bot.core_pos is not None and max(
        abs(claimed_pos.x - bot.core_pos.x),
        abs(claimed_pos.y - bot.core_pos.y),
    ) <= 2:
        return False

    if reserved_keys is None:
        reserved_keys = (
            {_pos_tuple(ct.get_position())}
            if hasattr(ct, "get_position")
            else {claimed_key}
        )

    marker_value = marker.create_pipeline_claim_marker(
        claimed_pos,
        current_round,
        ct.get_map_width(),
        ct.get_map_height(),
    )
    for direction in _claim_marker_directions(build_dir):
        marker_pos = claimed_pos.add(direction)
        if not _is_safe_pipeline_claim_marker_tile(
            bot,
            ct,
            marker_pos,
            claimed_pos,
            reserved_keys,
        ):
            continue
        ct.place_marker(marker_pos, marker_value)
        shared.add(claimed_key)
        bot.last_pipeline_claim_round = current_round
        bot.logger.log(f"shared pipeline claim for {claimed_key} at {marker_pos}")
        return True
    return False


def _record_built_pipeline_tile(
    bot,
    ct: Controller,
    pos: Position,
    build_dir,
    *,
    reserved_keys=None,
) -> None:
    pos_key = _pos_tuple(pos)
    bot.tiled_back_positions.add(pos_key)
    if not ENABLE_PIPELINE_CLAIM_MARKERS:
        return
    claimed = getattr(bot, "claimed_pipeline_positions", None)
    if claimed is None:
        claimed = set()
        bot.claimed_pipeline_positions = claimed
    claimed.add(pos_key)
    _try_share_pipeline_claim_marker(
        bot,
        ct,
        pos,
        build_dir,
        reserved_keys=reserved_keys,
    )


def _get_pending_build_pos(pending_build) -> tuple[int, int] | None:
    if pending_build is None:
        return None
    action_type = pending_build[0]
    if action_type == ActionType.CONVEYOR:
        return _pos_tuple(pending_build[1])
    elif action_type == ActionType.BRIDGE:
        return _pos_tuple(pending_build[1])
    return None


def _note_pending_build_stall(bot, ct: Controller, succeeded: bool) -> bool:
    """Track turns spent on a pending build. Returns True if the stall limit
    was reached and the pending build should be abandoned."""
    state = bot.pathfinding_state
    build_pos = _get_pending_build_pos(bot.pending_build)

    if succeeded or build_pos is None:
        state.pop("pending_build_stall_turns", None)
        state.pop("pending_build_stall_pos", None)
        return False

    if state.get("pending_build_stall_pos") != build_pos:
        state["pending_build_stall_pos"] = build_pos
        state["pending_build_stall_turns"] = 1
        return False

    state["pending_build_stall_turns"] = state.get("pending_build_stall_turns", 0) + 1

    if state["pending_build_stall_turns"] < PENDING_BUILD_STALL_LIMIT:
        return False

    if _fallback_direct_core_to_pipeline(bot, "pending build stalled"):
        return True

    # Stall limit reached — abandon the pending build and reroute.
    bot.logger.log(
        f"pending build stalled {state['pending_build_stall_turns']} turns at {build_pos}, abandoning"
    )
    state.setdefault("temporary_obstacles", {})[build_pos] = (
        ct.get_current_round() + PENDING_BUILD_TEMP_OBSTACLE_TTL
    )
    state["path"] = []
    state["planner_state"] = None
    state["last_replan_signature"] = None
    state.pop("pending_build_stall_turns", None)
    state.pop("pending_build_stall_pos", None)
    bot.pending_build = None
    bot.pending_bridge_plan = None
    bot.bridge_transit_path = None
    bot.bridge_transit_cooldown_until = -1
    if hasattr(bot, "saved_post_bridge_path"):
        bot.saved_post_bridge_path = []
    return True


def _execute_pending_build(bot, ct: Controller) -> bool:
    """Executes a queued build order if resources or obstacles previously prevented it."""
    if bot.pending_build is None:
        return False

    action_type = bot.pending_build[0]

    if action_type == ActionType.CONVEYOR:
        _, build_pos, build_dir = bot.pending_build
        if _visible_protected_pipeline_at(bot, ct, build_pos):
            if _visible_matching_friendly_conveyor(bot, ct, build_pos, build_dir):
                if _should_record_friendly_pipeline_progress(bot, build_pos):
                    build_key = _pos_tuple(build_pos)
                    bot.tiled_back_positions.add(build_key)
                    claimed = getattr(bot, "claimed_pipeline_positions", None)
                    if claimed is None:
                        claimed = set()
                        bot.claimed_pipeline_positions = claimed
                    claimed.add(build_key)
            else:
                _protect_pipeline_temp_obstacle(
                    bot,
                    ct,
                    build_pos,
                    "abandoning conflicting pending conveyor build",
                )
            bot.pending_build = None
            _note_pending_build_stall(bot, ct, succeeded=True)
            return False
        if _visible_matching_friendly_conveyor(bot, ct, build_pos, build_dir):
            _record_built_pipeline_tile(bot, ct, build_pos, build_dir)
            bot.pending_build = None
            _note_pending_build_stall(bot, ct, succeeded=True)
            return False
        if not ct.can_build_conveyor(build_pos, build_dir):
            _clear_obstacles_for_conveyor(bot, ct, build_pos, build_dir)
            bot.logger.log("can't execute pending conveyor build yet, maybe blocked?")
        if ct.can_build_conveyor(build_pos, build_dir):
            bot.logger.log(
                f"executing pending build of conveyor at {build_pos} toward {build_dir}"
            )
            ct.build_conveyor(build_pos, build_dir)
            _record_built_pipeline_tile(bot, ct, build_pos, build_dir)
            bot.pending_build = None
            _note_pending_build_stall(bot, ct, succeeded=True)
        elif _note_pending_build_stall(bot, ct, succeeded=False):
            return False  # Stall abandoned — let navigation run this turn
        return True

    elif action_type == ActionType.BRIDGE:
        _, start_pos, target_pos = bot.pending_build
        if _is_matching_bridge_present(ct, start_pos, target_pos):
            bot.logger.log(
                f"pending bridge from {start_pos} to {target_pos} is already built"
            )
            _record_built_pipeline_tile(bot, ct, start_pos, None)
            _record_built_pipeline_tile(bot, ct, target_pos, None)
            bot.pending_build = None
            _note_pending_build_stall(bot, ct, succeeded=True)
        elif (
            _visible_protected_pipeline_at(bot, ct, start_pos)
            or _visible_protected_pipeline_at(bot, ct, target_pos)
        ):
            protected_pos = (
                start_pos
                if _visible_protected_pipeline_at(bot, ct, start_pos)
                else target_pos
            )
            _protect_pipeline_temp_obstacle(
                bot,
                ct,
                protected_pos,
                "abandoning bridge over friendly pipeline",
            )
            bot.pending_build = None
            _note_pending_build_stall(bot, ct, succeeded=True)
            return False
        elif ct.can_build_bridge(start_pos, target_pos):
            bot.logger.log(
                f"executing pending build of bridge from {start_pos} to {target_pos}"
            )
            ct.build_bridge(start_pos, target_pos)
            _record_built_pipeline_tile(bot, ct, start_pos, None)
            _record_built_pipeline_tile(bot, ct, target_pos, None)
            bot.pending_build = None
            _note_pending_build_stall(bot, ct, succeeded=True)
        else:
            _clear_obstacles_for_conveyor(bot, ct, start_pos, None)
            bot.logger.log("blocked from building pending bridge, waiting...")
            if _note_pending_build_stall(bot, ct, succeeded=False):
                return False  # Stall abandoned — let navigation run this turn
        return True

    return False


def _clear_obstacles_for_conveyor(
    bot,
    ct: Controller,
    current_pos: Position,
    build_dir,
    allow_destroy_conveyors: bool = True,
):
    """Destroys markers (or misaligned friendly conveyors) to make way for a
    conveyor build on the same tile. Friendly roads are intentionally NOT
    destroyed — a conveyor build subsumes the road, so destroying first is
    wasted action cooldown."""
    tile_data = bot.grid.get(_pos_tuple(current_pos))
    if tile_data is None:
        return
    tile_team = tile_data.get("building_team")
    enemy_team = tile_team is not None and tile_team != ct.get_team()
    # destroy enemy under us
    if enemy_team:
        if ct.can_fire(current_pos):
            ct.fire(current_pos)
            bot.logger.log(f"Fired on enemy building at {current_pos} to clear path")
        return

    et = tile_data.get("building")
    if _visible_protected_pipeline_at(bot, ct, current_pos):
        _protect_pipeline_temp_obstacle(
            bot,
            ct,
            current_pos,
            "refusing to clear friendly transport",
        )
        return

    if (
        allow_destroy_conveyors
        and et == EntityType.CONVEYOR
        and tile_team == ct.get_team()
        and tile_data.get("building_dir") != build_dir
    ):
        if ct.can_destroy(current_pos):
            ct.destroy(current_pos)
            bot.logger.log(
                f"Destroyed unconnected misaligned conveyor at {current_pos} to clear path"
            )
        return

    # Roads get paved over directly — conveyor build consumes them.
    if et in CAN_DESTROY_TYPES:
        if ct.can_destroy(current_pos):
            ct.destroy(current_pos)
            bot.logger.log(
                f"Destroyed {et} at {current_pos} to clear path for conveyor"
            )
        return

    return


def _navigate_and_build(
    bot,
    ct: Controller,
    current_pos: Position,
    target_pos: Position,
):
    """Uses A* memory to look ahead and build conveyors pointing backward.

    This mode is intentionally not "move first, build later". The whole point
    is to interleave route planning, obstacle clearing, and lane construction so
    a newly placed harvester is more likely to end the trip with a live route.
    """

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
            active_temp_obs = {
                pos
                for pos, expiry in bot.pathfinding_state.get(
                    "temporary_obstacles", {}
                ).items()
                if expiry > ct.get_current_round()
            }
            active_temp_obs.discard((jump_target_pos.x, jump_target_pos.y))

            # `jon-5o` departure from `jon-5`: before paying for a second A*,
            # try a tiny exact transit plan. This keeps the same bridge policy
            # but avoids the worst same-turn search spikes.
            bot.bridge_transit_path = navigation.calculate_micro_plan(
                bot,
                ct,
                start=current_pos,
                target=jump_target_pos,
                known_obstacles=bot.pathfinding_state["known_obstacles"],
                temporary_obstacles=active_temp_obs,
                exact_only=True,
            )

            if bot.bridge_transit_path:
                bot.pending_bridge_plan = None
            elif navigation.get_available_astar_time_budget(bot) > 0:
                bot.stats["double_astar_turns"] += 1
                bot.bridge_transit_path = navigation.calculate_astar_path(
                    bot,
                    ct,
                    start=current_pos,
                    target=jump_target_pos,
                    known_obstacles=bot.pathfinding_state["known_obstacles"],
                    temporary_obstacles=active_temp_obs,
                    allow_bridges=False,
                )

                if bot.bridge_transit_path:
                    bot.pending_bridge_plan = None
                else:
                    # No non-bridge transit path exists — typical on
                    # spiral maps (cinnamon_roll, flowers, donut) where
                    # the bridge IS the only crossing over a thin wall
                    # arm. Rather than sitting in cooldown forever
                    # waiting for a transit that will never exist,
                    # queue the bridge build directly from current_pos
                    # and drop the transit attempt. The bridge handles
                    # resource flow across the wall; the builder does
                    # NOT need to physically cross.
                    bot.logger.log(
                        f"bridge transit unreachable from {current_pos} to "
                        f"{jump_target_pos}; queueing direct bridge build"
                    )
                    if ct.can_build_bridge(bridge_start, jump_target_pos):
                        ct.build_bridge(bridge_start, jump_target_pos)
                        _record_built_pipeline_tile(bot, ct, bridge_start, None)
                        _record_built_pipeline_tile(bot, ct, jump_target_pos, None)
                    else:
                        bot.pending_build = (
                            ActionType.BRIDGE,
                            bridge_start,
                            jump_target_pos,
                        )
                    bot.pending_bridge_plan = None
                    bot.pending_bridge_start = None
                    bot.pending_bridge_end = None
                    # Invalidate the cached A* path so the next turn
                    # replans with the bridge in place.
                    bot.pathfinding_state["path"] = []
                    bot.pathfinding_state["planner_state"] = None
                    return
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
        reserved_keys = _future_path_keys(current_pos, next_state.get("path", []))

        # Build under ourselves
        current_protected = _visible_protected_pipeline_at(bot, ct, current_pos)
        current_matches = _visible_matching_friendly_conveyor(
            bot,
            ct,
            current_pos,
            move_dir,
        )
        if current_protected and _should_record_friendly_pipeline_progress(bot, current_pos):
            bot.tiled_back_positions.add(_pos_tuple(current_pos))
        if current_protected and not current_matches:
            bot.logger.log(
                f"preserving friendly pipeline at {current_pos}; moving without retargeting it"
            )
        elif not ct.can_build_conveyor(current_pos, move_dir):
            _clear_obstacles_for_conveyor(bot, ct, current_pos, move_dir)
        if current_protected:
            pass
        elif ct.can_build_conveyor(current_pos, move_dir):
            ct.build_conveyor(current_pos, move_dir)
            _record_built_pipeline_tile(
                bot,
                ct,
                current_pos,
                move_dir,
                reserved_keys=reserved_keys,
            )
        else:
            current_cell = bot.grid.get(_pos_tuple(current_pos))
            if current_cell is None or (
                current_cell.get("building") != EntityType.CONVEYOR
                or current_cell.get("building_team") != ct.get_team()
                or current_cell.get("building_dir") != move_dir
            ):
                bot.pending_build = (ActionType.CONVEYOR, current_pos, move_dir)

        # Lookahead Building. Skipped under time pressure so we do not burn
        # the final slice of the budget on a speculative next-tile build when
        # we are about to TLE.
        governor = getattr(bot, "timing_governor", None)
        skip_lookahead = (
            governor is not None
            and not governor.has_budget_for(timing.LOOKAHEAD_BUILD_NS)
        )
        if skip_lookahead:
            utils.bump_profile(bot, "tiling_back_time_gated_lookahead")
        if next_action is not None and not skip_lookahead:
            next_action_type, next_pos_best_dir = next_action
            next_pos = current_pos.add(move_dir)

            next_matches = (
                next_action_type == ActionType.CONVEYOR
                and _visible_matching_friendly_conveyor(
                    bot,
                    ct,
                    next_pos,
                    next_pos_best_dir,
                )
            )
            if _visible_protected_pipeline_at(bot, ct, next_pos):
                if next_matches:
                    if _should_record_friendly_pipeline_progress(bot, next_pos):
                        bot.tiled_back_positions.add(_pos_tuple(next_pos))
                else:
                    next_state["known_obstacles"].add(_pos_tuple(next_pos))
                    bot.pathfinding_state.setdefault("temporary_obstacles", {})[
                        _pos_tuple(next_pos)
                    ] = ct.get_current_round() + PENDING_BUILD_TEMP_OBSTACLE_TTL
                    bot.logger.log(
                        f"preserving friendly pipeline at {next_pos}; skipping lookahead build"
                    )
            else:
                # Lookahead hygiene: only clear obstacles at next_pos when
                # the build actually cannot proceed. Unconditionally
                # destroying was wasting actions on roads/markers the build
                # didn't need cleared.
                if next_action_type == ActionType.CONVEYOR and not ct.can_build_conveyor(
                    next_pos, next_pos_best_dir
                ):
                    _clear_obstacles_for_conveyor(
                        bot,
                        ct,
                        next_pos,
                        next_pos_best_dir,
                    )
                elif next_action_type == ActionType.BRIDGE and not ct.can_build_bridge(
                    next_pos, next_pos_best_dir
                ):
                    _clear_obstacles_for_conveyor(
                        bot,
                        ct,
                        next_pos,
                        next_pos_best_dir,
                    )
                if next_action_type == ActionType.CONVEYOR:
                    if ct.can_build_conveyor(next_pos, next_pos_best_dir):
                        ct.build_conveyor(next_pos, next_pos_best_dir)
                        _record_built_pipeline_tile(
                            bot,
                            ct,
                            next_pos,
                            next_pos_best_dir,
                            reserved_keys=reserved_keys,
                        )
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
                        _record_built_pipeline_tile(
                            bot,
                            ct,
                            next_pos,
                            None,
                            reserved_keys=reserved_keys,
                        )
                        next_state["known_obstacles"].discard((next_pos.x, next_pos.y))
                        # bot.pathfinding_state = next_state

        # Execute move
        if bot.pending_build is None and ct.can_move(move_dir):
            ct.move(move_dir)
            if bot.pathfinding_state["path"]:
                bot.pathfinding_state["path"].pop(0)
        elif bot.pending_build is None and move_dir is not None:
            # Move blocked — only reroute around a friendly builder if they
            # outrank us on id or are attached to a harvester route (jon-6
            # yield policy). Otherwise wait for them to move. Shorter TTL so
            # stale obstacles clear quickly.
            blocked_pos = current_pos.add(move_dir)
            blocked_key = _pos_tuple(blocked_pos)
            blocked_data = bot.grid.get(blocked_key)
            if (
                blocked_data is not None
                and blocked_data.get("entity") is EntityType.BUILDER_BOT
                and blocked_data.get("entity_team") == ct.get_team()
            ):
                if navigation._should_yield_around_friendly_blocker(  # noqa: SLF001
                    bot, ct, blocked_pos, blocked_data
                ):
                    bot.pathfinding_state.setdefault("temporary_obstacles", {})[
                        blocked_key
                    ] = ct.get_current_round() + 3


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


def _share_connected_harvester_marker(bot, ct: Controller):
    if not ENABLE_CONNECTED_HARVESTER_MARKERS:
        return
    if ct.get_position().distance_squared(bot.core_pos) > 2:
        return
    if bot.last_harvester_pos is None:
        return

    harvester_key = (bot.last_harvester_pos.x, bot.last_harvester_pos.y)
    if harvester_key in bot.shared_connected_harvester_positions:
        return

    marker_value = marker.create_connected_harvester_marker(
        bot.last_harvester_pos,
        ct.get_current_round(),
        ct.get_map_width(),
        ct.get_map_height(),
    )
    if utils.place_connected_harvester_marker_around(
        ct,
        ct.get_position(),
        marker_value,
    ):
        bot.shared_connected_harvester_positions.add(harvester_key)
        bot.logger.log(f"Shared connected harvester marker for {harvester_key}")


def _abandon_tiling_back(bot, ct: Controller):
    """Give up on the current tiling-back attempt and free the builder."""
    round_now = ct.get_current_round()

    # Blacklist the harvester position with escalating TTL.  After
    # NAV_STALL_BLACKLIST_PERMANENT_AFTER repeated failures on the same
    # harvester, the blacklist becomes effectively permanent (rest of game).
    if bot.last_harvester_pos is not None and bot.tiling_back_origin_kind == "HARVESTER":
        hkey = (bot.last_harvester_pos.x, bot.last_harvester_pos.y)
        fail_counts = getattr(bot, "tiling_back_fail_counts", None)
        if fail_counts is None:
            fail_counts = {}
            bot.tiling_back_fail_counts = fail_counts
        fail_counts[hkey] = fail_counts.get(hkey, 0) + 1
        failures = fail_counts[hkey]

        if failures >= NAV_STALL_BLACKLIST_PERMANENT_AFTER:
            ttl = 500
        else:
            ttl = NAV_STALL_BLACKLIST_BASE_TTL + NAV_STALL_BLACKLIST_ESCALATION * (failures - 1)

        bot.ore_target_blacklist[hkey] = round_now + ttl
        bot.logger.log(
            f"tiling_back nav stall: blacklisting harvester {hkey} for {ttl} turns "
            f"(failure #{failures})"
        )

    # Clean up all tiling-back bookkeeping.
    bot.pending_build = None
    bot.pending_bridge_plan = None
    bot.bridge_transit_path = None
    bot.bridge_transit_cooldown_until = -1
    _clear_core_return_state(bot)
    if hasattr(bot, "saved_post_bridge_path"):
        bot.saved_post_bridge_path = []
    bot.pathfinding_state["path"] = []
    bot.pathfinding_state["planner_state"] = None
    bot.pathfinding_state["last_replan_signature"] = None
    bot.pathfinding_state.pop("tiling_back_nav_stall_turns", None)
    bot.pathfinding_state.pop("tiling_back_nav_stall_pos", None)
    bot.pathfinding_state.pop("tiling_back_pos_history", None)
    bot.pathfinding_state.pop("tiling_back_osc_count", None)
    bot.pathfinding_state.pop("pending_build_stall_turns", None)
    bot.pathfinding_state.pop("pending_build_stall_pos", None)

    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.logger.log("tiling_back nav stall: abandoned, switching to FINDING_ORE")


NAV_PING_PONG_HISTORY = 6
NAV_PING_PONG_UNIQUE_THRESHOLD = 2


def _note_nav_stall(bot, ct: Controller, pos_before: Position, pos_after: Position) -> bool:
    """Track turns without REAL progress in TILING_BACK.  Detects both
    stationary stalls (pos unchanged) and ping-pong oscillation (builder
    alternates between a small set of positions).  Returns True and triggers
    abandonment if the stall limit is reached."""
    state = bot.pathfinding_state
    pos_key = _pos_tuple(pos_after)

    # --- stationary detection (original) ---
    if pos_before == pos_after:
        if state.get("tiling_back_nav_stall_pos") != pos_key:
            state["tiling_back_nav_stall_pos"] = pos_key
            state["tiling_back_nav_stall_turns"] = 1
        else:
            state["tiling_back_nav_stall_turns"] = state.get("tiling_back_nav_stall_turns", 0) + 1

        if state["tiling_back_nav_stall_turns"] >= NAV_STALL_LIMIT:
            _abandon_tiling_back(bot, ct)
            return True
        if state["tiling_back_nav_stall_turns"] >= DIRECT_CORE_FALLBACK_STALL_LIMIT:
            if _fallback_direct_core_to_pipeline(bot, "stationary route stall"):
                return False
    else:
        state.pop("tiling_back_nav_stall_turns", None)
        state.pop("tiling_back_nav_stall_pos", None)

    # --- ping-pong / oscillation detection ---
    # Only track oscillation when the builder actually moved this turn.
    # Stationary stalls are handled by the counter above.
    if pos_before != pos_after:
        history = state.get("tiling_back_pos_history")
        if history is None:
            history = []
            state["tiling_back_pos_history"] = history
        history.append(pos_key)
        if len(history) > NAV_PING_PONG_HISTORY:
            history.pop(0)

        if len(history) >= NAV_PING_PONG_HISTORY:
            unique_positions = set(history)
            if len(unique_positions) <= NAV_PING_PONG_UNIQUE_THRESHOLD:
                osc_count = state.get("tiling_back_osc_count", 0) + 1
                state["tiling_back_osc_count"] = osc_count
                if osc_count >= NAV_STALL_LIMIT // NAV_PING_PONG_HISTORY:
                    _abandon_tiling_back(bot, ct)
                    return True
                if osc_count >= max(1, DIRECT_CORE_FALLBACK_STALL_LIMIT // NAV_PING_PONG_HISTORY):
                    if _fallback_direct_core_to_pipeline(bot, "route oscillation"):
                        return False
            else:
                state["tiling_back_osc_count"] = 0
    return False


def execute(bot, ct: Controller):
    current_pos = ct.get_position()
    pos_before = current_pos
    _update_return_target_while_tiling(bot, ct, current_pos)

    target_pos = (
        bot.return_target_pos if bot.return_target_pos is not None else bot.core_pos
    )
    target_kind = bot.return_target_kind

    if target_kind == TargetKind.CORE and target_pos is None:
        target_pos = _select_core_return_target(bot, ct, current_pos)

    bot.logger.log(
        f"state: pending build {bot.pending_build}, return target {bot.return_target_pos}, kind {bot.return_target_kind}"
    )

    if _ensure_core_slot_exit(bot, ct, current_pos, target_pos, target_kind):
        return

    if _is_at_core(bot, ct, current_pos, target_pos, target_kind):
        _share_connected_conveyor_marker(bot, ct)
        _share_connected_harvester_marker(bot, ct)
        _clear_core_return_state(bot)
        bot.builder_mode = BuilderMode.FINDING_ORE
        return

    if _check_connect_to_conveyor(bot, ct, current_pos, target_pos, target_kind):
        _share_connected_conveyor_marker(bot, ct)
        _share_connected_harvester_marker(bot, ct)
        _clear_core_return_state(bot)
        bot.builder_mode = BuilderMode.FINDING_ORE
        return

    # 1. Check Pending Actions
    executed = _execute_pending_build(bot, ct)

    # 2. Main Action: Move and Build
    if not executed:
        _navigate_and_build(bot, ct, current_pos, target_pos)

    # 3. Check End Conditions
    current_pos = ct.get_position()
    if _ensure_core_slot_exit(bot, ct, current_pos, target_pos, target_kind):
        return

    if _is_at_core(bot, ct, current_pos, target_pos, target_kind):
        _share_connected_conveyor_marker(bot, ct)
        _share_connected_harvester_marker(bot, ct)
        _clear_core_return_state(bot)
        bot.builder_mode = BuilderMode.FINDING_ORE
        return

    if _check_connect_to_conveyor(bot, ct, current_pos, target_pos, target_kind):
        _share_connected_conveyor_marker(bot, ct)
        _share_connected_harvester_marker(bot, ct)
        _clear_core_return_state(bot)
        bot.builder_mode = BuilderMode.FINDING_ORE
        return

    # 4. Track navigation progress — catch builders stuck in navigate-and-build
    _note_nav_stall(bot, ct, pos_before, current_pos)
