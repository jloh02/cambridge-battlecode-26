from cambc import (
    Controller,
    EntityType,
    Environment,
    GameConstants,
    Position,
)
import math
import time
import assault
import marker
import timing
import utils
from states import BuilderMode

MAX_VISION_ASSUMPTION = math.sqrt(GameConstants.BUILDER_BOT_VISION_RADIUS_SQ) - 1
CHUNK_SIZE = max(1, int(MAX_VISION_ASSUMPTION))
EXPLORE_CLAIM_TTL = 20
ASSAULT_CLAIM_TTL = 12
REMOTE_CACHE_TTL = 80
ORE_MARKER_TTL = 120
PIPELINE_CLAIM_TTL = 32
FAST_SCAN_RADIUS_SQ = 9

# Entities that do not block movement
PASSABLE_ENTITIES = {
    EntityType.ROAD,
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.MARKER,
    EntityType.CORE,
    EntityType.BUILDER_BOT,
}


def _friendly_harvester_positions(bot, my_team) -> list[tuple[int, int]]:
    utils.bump_profile(bot, "perception_friendly_harvester_scan_calls")
    utils.bump_profile(bot, "perception_grid_entries_scanned", len(bot.grid))
    harvesters = []
    for key, data in bot.grid.items():
        if data.get("building") == EntityType.HARVESTER and data.get("building_team") == my_team:
            harvesters.append(key)
            continue
        if data.get("entity") == EntityType.HARVESTER and data.get("entity_team") == my_team:
            harvesters.append(key)
    utils.max_profile(bot, "perception_friendly_harvesters_found_peak", len(harvesters))
    return harvesters


def _all_harvester_positions(bot) -> dict[tuple[int, int], object]:
    utils.bump_profile(bot, "perception_all_harvester_scan_calls")
    utils.bump_profile(bot, "perception_grid_entries_scanned", len(bot.grid))
    harvesters = {}
    for key, data in bot.grid.items():
        if data.get("building") == EntityType.HARVESTER:
            harvesters[key] = data.get("building_team")
        elif data.get("entity") == EntityType.HARVESTER:
            harvesters[key] = data.get("entity_team")
    utils.max_profile(bot, "perception_all_harvesters_found_peak", len(harvesters))
    return harvesters


_CONVEYOR_TYPES = frozenset({
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
})

_CARDINAL_DELTAS = [(0, -1), (1, 0), (0, 1), (-1, 0)]


def _note_known_env_tile(bot, previous_tile_data: dict | None, env) -> None:
    if env is None:
        return
    if previous_tile_data is not None and previous_tile_data.get("env") is not None:
        return
    bot.grid_env_known_count = getattr(bot, "grid_env_known_count", 0) + 1


def _count_adjacent_conveyors(
    bot,
    ct: Controller,
    harvester_pos: tuple[int, int],
    my_team=None,
) -> int:
    hx, hy = harvester_pos
    count = 0
    if my_team is None:
        my_team = ct.get_team()
    grid_get = bot.grid.get

    for dx, dy in _CARDINAL_DELTAS:
        neighbor_data = grid_get((hx + dx, hy + dy))
        if neighbor_data is not None:
            if neighbor_data.get("building") in _CONVEYOR_TYPES and neighbor_data.get("building_team") == my_team:
                count += 1

    return count


def _get_nearby_tiles(bot, ct: Controller, radius_sq: int | None = None):
    if radius_sq is None:
        return list(ct.get_nearby_tiles())

    try:
        return list(ct.get_nearby_tiles(radius_sq))
    except TypeError:
        current_pos = ct.get_position()
        return [
            pos
            for pos in ct.get_nearby_tiles()
            if current_pos.distance_squared(pos) <= radius_sq
        ]


_STATIC_ENV_CACHE_OK = frozenset({Environment.EMPTY, Environment.WALL})


def _collect_visible_snapshot(
    bot,
    ct: Controller,
    nearby_tiles,
    *,
    include_building_health: bool = True,
):
    """Resumable, stale-first perception snapshot.

    Three layered SDK-call reductions relative to the previous version:

    1. Terrain env is cached for WALL/EMPTY tiles. Those environments never
       change during a game, so once a tile has been observed we skip the
       ``get_tile_env`` call on subsequent full scans. Ore tiles are always
       re-queried because harvesting can deplete them to EMPTY.
    2. Per-tile ``get_tile_builder_bot_id`` is skipped entirely. Builder bots
       visible inside the vision ring already show up in ``get_nearby_units()``
       (which this function still calls), so we let the unit loop populate
       builder-bot entries in ``nearby_cache``/``nearby_units`` instead of
       paying one extra SDK call per visible tile. For ~60 visible tiles this
       saves ~55 SDK calls on every full perception turn.
    3. Building-id reuse: building type/team/direction/bridge_target are
       immutable for a given id, so when this turn's tile still has the
       same building_id we previously stored we hydrate everything except
       HP from cached grid data. With ~40 stable buildings this saves
       another ~120 SDK calls per full scan.

    **Anytime resumption** (the important piece): we sort the input tiles
    by their previously-recorded ``last_seen`` round, oldest first. We then
    make SDK calls in that order, budget-gated. When the remaining hard
    budget drops below ``SNAPSHOT_RESERVE_NS`` we stop paying for SDK calls
    but still pass the remaining tiles through a cheap hydration path: for
    any tile that already has grid data from a previous turn, we synthesise
    its ``(pos, env, building_id, None)`` entry from the stored tile_data
    so the full vision set still flows downstream — enemies, obstacles and
    conveyor topology are preserved from the last good scan. Tiles never
    seen before are still SDK-queried because there is nothing cached to
    fall back on. Over multiple turns the staleness ordering rotates
    through every visible tile, so each position is eventually refreshed.
    No work is dropped, only deferred."""
    entity_type_cache: dict[int, EntityType] = {}
    entity_team_cache: dict[int, object] = {}
    visible_tiles: list[tuple[Position, Environment, int | None, int | None]] = []
    nearby_buildings: list[int] = []
    nearby_units: list[int] = []
    nearby_cache: dict[int, dict] = {}
    my_team = ct.get_team()  # Cache once — was called per-building before.
    utils.bump_profile(bot, "perception_snapshot_calls")
    utils.max_profile(bot, "perception_nearby_tiles_peak", len(nearby_tiles))

    # Local refs for hot-path SDK calls.
    _get_entity_type = ct.get_entity_type
    _get_team = ct.get_team
    _get_tile_env = ct.get_tile_env
    _get_tile_building_id = ct.get_tile_building_id
    _grid_get = bot.grid.get
    _static_envs = _STATIC_ENV_CACHE_OK
    _env_cache_hits = 0

    def cached_entity_type(entity_id: int) -> EntityType:
        entity_type = entity_type_cache.get(entity_id)
        if entity_type is None:
            entity_type = _get_entity_type(entity_id)
            entity_type_cache[entity_id] = entity_type
        return entity_type

    def cached_entity_team(entity_id: int):
        entity_team = entity_team_cache.get(entity_id)
        if entity_team is None:
            entity_team = _get_team(entity_id)
            entity_team_cache[entity_id] = entity_team
        return entity_team

    _CONVEYOR = EntityType.CONVEYOR
    _SPLITTER = EntityType.SPLITTER
    _ARMOURED_CONVEYOR = EntityType.ARMOURED_CONVEYOR
    _BRIDGE = EntityType.BRIDGE

    # Fetch anytime gate state up front — stale-first sort conditions on it.
    governor = getattr(bot, "timing_governor", None)
    hard_deadline = getattr(bot, "turn_hard_deadline_ns", 0)
    snapshot_reserve_ns = timing.SNAPSHOT_RESERVE_NS
    check_interval = timing.SNAPSHOT_CHECK_INTERVAL
    _time_ns = time.time_ns
    sdk_budget_exhausted = False
    deferred_positions: set[tuple[int, int]] = set()

    # Stale-first ordering: only reorder when the governor is present AND
    # the input is big enough to benefit from truncation. This keeps tests
    # (which usually omit the governor) and small fast scans operating on
    # their original tile order.
    if governor is not None and len(nearby_tiles) > check_interval:
        def _staleness_key(pos):
            cached = _grid_get((pos.x, pos.y))
            if cached is None:
                return -1
            return cached.get("last_seen", -1)

        ordered_tiles = sorted(nearby_tiles, key=_staleness_key)
    else:
        ordered_tiles = nearby_tiles

    for idx, pos in enumerate(ordered_tiles):
        if (
            not sdk_budget_exhausted
            and governor is not None
            and idx > 0
            and (idx % check_interval) == 0
            and hard_deadline - _time_ns() < snapshot_reserve_ns
        ):
            sdk_budget_exhausted = True

        cached_tile = _grid_get((pos.x, pos.y))

        if sdk_budget_exhausted and cached_tile is not None:
            # Cheap hydration path: reuse everything we already know for
            # this tile. No SDK calls. This tile is NOT added to
            # visible_tiles — _update_master_grid only rewrites scanned
            # tiles. Instead we record its position in deferred_positions
            # so the downstream visible_positions union stays complete
            # (enemy/obstacle tracking still sees the tile) while leaving
            # the grid data and last_seen timestamp untouched. Next turn
            # this tile's stale last_seen will sort it ahead of the tiles
            # we did refresh this turn, so it gets its fresh scan then.
            deferred_positions.add((pos.x, pos.y))
            cached_building_id = cached_tile.get("building_id")
            if cached_building_id is not None and cached_tile.get("building") is not None:
                cached_b_type = cached_tile.get("building")
                cached_team = cached_tile.get("building_team")
                building_info = {
                    "id": cached_building_id,
                    "pos": pos,
                    "type": cached_b_type,
                    "team": cached_team,
                }
                if cached_b_type is _CONVEYOR or cached_b_type is _SPLITTER or cached_b_type is _ARMOURED_CONVEYOR:
                    building_info["direction"] = cached_tile.get("building_dir")
                elif cached_b_type is _BRIDGE:
                    building_info["bridge_target"] = cached_tile.get("bridge_target")
                if include_building_health and cached_team == my_team:
                    cached_hp = cached_tile.get("building_hp")
                    cached_max_hp = cached_tile.get("building_max_hp")
                    if cached_hp is not None:
                        building_info["hp"] = cached_hp
                    if cached_max_hp is not None:
                        building_info["max_hp"] = cached_max_hp
                nearby_cache[cached_building_id] = building_info
                nearby_buildings.append(cached_building_id)
            continue

        # Fresh SDK path — either we still have budget, or we have no cached
        # data for this tile (never seen) and must query to learn anything.
        if cached_tile is not None:
            cached_env = cached_tile.get("env")
            if cached_env in _static_envs:
                env = cached_env
                _env_cache_hits += 1
            else:
                env = _get_tile_env(pos)
        else:
            env = _get_tile_env(pos)
        building_id = _get_tile_building_id(pos)
        # builder_bot_id is populated via get_nearby_units() below instead of
        # paying a per-tile get_tile_builder_bot_id call.
        builder_bot_id = None
        visible_tiles.append((pos, env, building_id, builder_bot_id))

        if building_id is not None:
            cached_for_reuse = (
                cached_tile is not None
                and cached_tile.get("building_id") == building_id
                and cached_tile.get("building") is not None
                and cached_tile.get("building_team") is not None
            )
            if cached_for_reuse:
                b_type = cached_tile.get("building")
                building_team = cached_tile.get("building_team")
                building_info = {
                    "id": building_id,
                    "pos": pos,
                    "type": b_type,
                    "team": building_team,
                }
                if b_type is _CONVEYOR or b_type is _SPLITTER or b_type is _ARMOURED_CONVEYOR:
                    building_info["direction"] = cached_tile.get("building_dir")
                elif b_type is _BRIDGE:
                    building_info["bridge_target"] = cached_tile.get("bridge_target")
                utils.bump_profile(bot, "perception_building_id_cache_hits")
            else:
                b_type = cached_entity_type(building_id)
                building_team = cached_entity_team(building_id)
                building_info = {
                    "id": building_id,
                    "pos": pos,
                    "type": b_type,
                    "team": building_team,
                }
                if b_type is _CONVEYOR or b_type is _SPLITTER or b_type is _ARMOURED_CONVEYOR:
                    utils.bump_profile(bot, "perception_building_direction_reads")
                    building_info["direction"] = ct.get_direction(building_id)
                elif b_type is _BRIDGE:
                    utils.bump_profile(bot, "perception_bridge_target_reads")
                    building_info["bridge_target"] = ct.get_bridge_target(building_id)
            # HP is dynamic even for the same building_id — always re-query.
            if include_building_health and building_team == my_team:
                utils.bump_profile(bot, "perception_building_health_reads")
                building_info["hp"] = ct.get_hp(building_id)
                building_info["max_hp"] = ct.get_max_hp(building_id)
            nearby_cache[building_id] = building_info
            nearby_buildings.append(building_id)

    # Builder bots (and any other visible units) are collected here instead of
    # via per-tile get_tile_builder_bot_id calls above. get_nearby_units() is a
    # single SDK call that returns all visible units, so we save one SDK call
    # per visible tile in exchange for a few get_position calls per visible
    # builder — typically ~55 fewer SDK calls per full scan.
    if _env_cache_hits:
        utils.bump_profile(bot, "perception_env_cache_hits", _env_cache_hits)
    if deferred_positions:
        utils.bump_profile(
            bot, "perception_snapshot_deferred_tiles", len(deferred_positions)
        )
    # Stash deferred positions on the bot so scan_around() can merge them
    # into visible_positions after _update_master_grid runs.
    bot._snapshot_deferred_positions = deferred_positions
    for unit_id in ct.get_nearby_units():
        if unit_id in nearby_cache:
            continue

        entity_type = cached_entity_type(unit_id)
        entity_info = {
            "pos": ct.get_position(unit_id),
            "type": entity_type,
            "team": cached_entity_team(unit_id),
        }
        nearby_cache[unit_id] = entity_info
        nearby_units.append(unit_id)

    utils.max_profile(bot, "perception_visible_tiles_peak", len(visible_tiles))
    utils.max_profile(bot, "perception_visible_buildings_peak", len(nearby_buildings))
    utils.max_profile(bot, "perception_visible_units_peak", len(nearby_units))
    return visible_tiles, nearby_buildings, nearby_units, nearby_cache


GRID_PRUNE_INTERVAL = 50
GRID_PRUNE_TTL = 200


def _prune_stale_grid_entries(bot, current_round: int) -> None:
    """Remove grid entries not seen for >GRID_PRUNE_TTL turns. Caps late-game
    grid size and keeps known_obstacles from growing unboundedly.

    Exempt: known friendly conveyors (critical for topology refresh and
    return targeting) and tracked harvesters (needed for economy logic)."""
    cutoff = current_round - GRID_PRUNE_TTL
    grid = bot.grid
    known_obstacles = bot.pathfinding_state["known_obstacles"]
    tracked_harvesters = getattr(bot, "tracked_harvesters", {})
    known_conveyors = bot.known_friendly_conveyors
    stale_keys = [
        key for key, data in grid.items()
        if data.get("last_seen", 0) < cutoff
        and key not in known_conveyors
        and key not in tracked_harvesters
    ]
    for key in stale_keys:
        if grid[key].get("env") is not None:
            bot.grid_env_known_count = max(
                0,
                getattr(bot, "grid_env_known_count", 0) - 1,
            )
        del grid[key]
        known_obstacles.discard(key)
    if stale_keys:
        utils.bump_profile(bot, "perception_grid_pruned_entries", len(stale_keys))


def scan_around(bot, ct: Controller, *, fast: bool = False, assault_mode: bool = False):
    """Main perception entry point.

    The order matters: first refresh the coarse exploration view, then write
    raw observations into the remembered grid, then decode marker hints, and
    only after that rebuild the derived state used by the current mode.
    """
    utils.bump_profile(bot, "perception_scan_calls")

    # Grid pruning still disabled: even with conveyor/harvester exemption,
    # topology refresh reads grid data for tiles ADJACENT to conveyors
    # (to check building types/directions), and those adjacencies get
    # pruned. Enabling this breaks economy on large maps.
    utils.set_profile(bot, "perception_scan_mode", "fast" if fast else "full")
    utils.set_profile(bot, "perception_assault_mode", int(assault_mode))
    include_building_health = not assault_mode and getattr(bot, "builder_mode", None) != BuilderMode.TILING_BACK
    scan_start = time.time_ns() if utils.DEBUG_TURN_PROFILE else 0
    if fast:
        # `jon-5o` departure from `jon-5`: stable tiling turns only refresh a
        # tight local window, then rely on the existing remembered map for the
        # rest. This preserves the same route-building policy with fewer
        # controller calls in the steady state.
        _scan_local_fast(
            bot,
            ct,
            include_building_health=include_building_health,
        )
        if scan_start:
            utils.bump_profile(bot, "perception_scan_ns", time.time_ns() - scan_start)
        return

    nearby_tiles = _get_nearby_tiles(bot, ct)
    utils.max_profile(bot, "perception_nearby_tiles_peak", len(nearby_tiles))
    snapshot_start = time.time_ns() if utils.DEBUG_TURN_PROFILE else 0
    visible_tiles, nearby_buildings, nearby_units, nearby_cache = (
        _collect_visible_snapshot(
            bot,
            ct,
            nearby_tiles,
            include_building_health=include_building_health,
        )
    )
    if snapshot_start:
        utils.bump_profile(bot, "perception_snapshot_ns", time.time_ns() - snapshot_start)

    chunks_start = time.time_ns() if utils.DEBUG_TURN_PROFILE else 0
    _update_exploration_chunks(bot, ct, visible_tiles)
    if chunks_start:
        utils.bump_profile(bot, "perception_chunk_update_ns", time.time_ns() - chunks_start)
    # Anytime time gate: if the snapshot already consumed most of the budget,
    # skip marker scanning and the expensive connected-conveyor refresh. The
    # bot still runs core grid/obstacle/enemy inference so movement and
    # defense remain coherent; the skipped work simply waits for the next
    # full perception turn that has enough budget.
    governor = getattr(bot, "timing_governor", None)
    time_pressured = (
        governor is not None
        and not governor.has_budget_for(timing.PERCEPTION_OPTIONAL_NS)
    )
    if not time_pressured:
        marker_start = time.time_ns() if utils.DEBUG_TURN_PROFILE else 0
        _scan_nearby_markers(bot, ct, nearby_buildings, nearby_cache)
        if marker_start:
            utils.bump_profile(bot, "perception_marker_ns", time.time_ns() - marker_start)
    else:
        utils.bump_profile(bot, "perception_time_gated_markers")
    grid_start = time.time_ns() if utils.DEBUG_TURN_PROFILE else 0
    _update_master_grid(bot, ct, visible_tiles, nearby_units, nearby_cache)
    if grid_start:
        utils.bump_profile(bot, "perception_grid_update_ns", time.time_ns() - grid_start)
    # Resumable anytime merge: deferred tiles (we ran out of SDK budget and
    # kept last turn's data) still need to appear in bot.visible_positions
    # so that _infer_state_from_grid processes them. Their grid data is
    # untouched, so inference reads cached values — correct for "stale but
    # still believable" state. Scanned tiles on future turns will bubble up
    # naturally via the staleness ordering.
    deferred_positions = getattr(bot, "_snapshot_deferred_positions", None)
    if deferred_positions:
        bot.visible_positions.update(deferred_positions)
        bot._snapshot_deferred_positions = None
    infer_start = time.time_ns() if utils.DEBUG_TURN_PROFILE else 0
    _infer_state_from_grid(
        bot,
        ct,
        nearby_units,
        nearby_cache,
        refresh_connected=(not assault_mode and not time_pressured),
    )
    if infer_start:
        utils.bump_profile(bot, "perception_infer_ns", time.time_ns() - infer_start)
    if scan_start:
        utils.bump_profile(bot, "perception_scan_ns", time.time_ns() - scan_start)


def _scan_local_fast(
    bot,
    ct: Controller,
    *,
    include_building_health: bool = True,
):
    utils.bump_profile(bot, "perception_fast_scan_calls")
    nearby_tiles = _get_nearby_tiles(bot, ct, FAST_SCAN_RADIUS_SQ)
    utils.max_profile(bot, "perception_fast_tiles_peak", len(nearby_tiles))
    current_round = ct.get_current_round()
    visible_tiles = []
    visible_positions = set()
    nearby_buildings = []
    nearby_entities = []
    nearby_cache = {}
    bot.bot_locations.clear()
    bot.bot_locations.add((ct.get_position().x, ct.get_position().y))
    get_tile_builder_bot_id = getattr(ct, "get_tile_builder_bot_id", None)
    my_team = ct.get_team()
    tile_loop_start = time.time_ns() if utils.DEBUG_TURN_PROFILE else 0

    grid = bot.grid
    _clear = _CLEAR_DYNAMIC
    _HARVESTER = EntityType.HARVESTER
    tracked_harvesters = getattr(bot, "tracked_harvesters", None)
    if tracked_harvesters is None:
        tracked_harvesters = {}
        bot.tracked_harvesters = tracked_harvesters

    for pos in nearby_tiles:
        env = ct.get_tile_env(pos)
        pos_tuple = (pos.x, pos.y)
        builder_bot_id = (
            get_tile_builder_bot_id(pos) if get_tile_builder_bot_id is not None else None
        )
        building_id = ct.get_tile_building_id(pos)
        visible_tiles.append((pos, env, building_id, builder_bot_id))
        visible_positions.add(pos_tuple)
        tile_data = grid.get(pos_tuple)
        _note_known_env_tile(bot, tile_data, env)
        if tile_data is None:
            tile_data = {}
            grid[pos_tuple] = tile_data
        else:
            # Incremental harvester removal before clearing.
            old_b = tile_data.get("building")
            old_e = tile_data.get("entity")
            if old_b is _HARVESTER or old_e is _HARVESTER:
                tracked_harvesters.pop(pos_tuple, None)
        tile_data.update(_clear)
        tile_data["env"] = env
        tile_data["last_seen"] = current_round

        if building_id is not None:
            b_type = ct.get_entity_type(building_id)
            building_team = ct.get_team(building_id)
            nearby_buildings.append(building_id)
            building_info = {
                "id": building_id,
                "pos": pos,
                "type": b_type,
                "team": building_team,
            }
            nearby_cache[building_id] = building_info
            tile_data["building"] = b_type
            tile_data["building_team"] = building_team
            tile_data["building_id"] = building_id
            if include_building_health and building_team == my_team:
                hp = ct.get_hp(building_id)
                max_hp = ct.get_max_hp(building_id)
                tile_data["building_hp"] = hp
                tile_data["building_max_hp"] = max_hp
                building_info["hp"] = hp
                building_info["max_hp"] = max_hp
            if b_type in {EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.ARMOURED_CONVEYOR}:
                build_dir = ct.get_direction(building_id)
                tile_data["building_dir"] = build_dir
                building_info["direction"] = build_dir
            elif b_type == EntityType.BRIDGE:
                bridge_target = ct.get_bridge_target(building_id)
                tile_data["bridge_target"] = bridge_target
                building_info["bridge_target"] = bridge_target
            # Incremental harvester insertion.
            if b_type is _HARVESTER:
                tracked_harvesters[pos_tuple] = building_team

        if builder_bot_id is None:
            continue

        tile_data["id"] = builder_bot_id
        tile_data["entity"] = EntityType.BUILDER_BOT
        tile_data["entity_team"] = ct.get_team(builder_bot_id)
        nearby_entities.append(builder_bot_id)
        nearby_cache[builder_bot_id] = {
            "pos": pos,
            "type": EntityType.BUILDER_BOT,
            "team": tile_data["entity_team"],
        }
        if tile_data["entity_team"] == my_team:
            bot.bot_locations.add(pos_tuple)

    if tile_loop_start:
        utils.bump_profile(bot, "perception_fast_tile_loop_ns", time.time_ns() - tile_loop_start)
    utils.max_profile(bot, "perception_fast_visible_tiles_peak", len(visible_tiles))
    utils.max_profile(bot, "perception_fast_visible_positions_peak", len(visible_positions))
    utils.max_profile(bot, "perception_fast_buildings_peak", len(nearby_buildings))
    utils.max_profile(bot, "perception_fast_units_peak", len(nearby_entities))
    chunks_start = time.time_ns() if utils.DEBUG_TURN_PROFILE else 0
    _update_exploration_chunks(bot, ct, visible_tiles)
    if chunks_start:
        utils.bump_profile(bot, "perception_chunk_update_ns", time.time_ns() - chunks_start)
    marker_start = time.time_ns() if utils.DEBUG_TURN_PROFILE else 0
    _scan_nearby_markers(bot, ct, nearby_buildings, nearby_cache)
    if marker_start:
        utils.bump_profile(bot, "perception_marker_ns", time.time_ns() - marker_start)
    bot.visible_positions = visible_positions
    infer_start = time.time_ns() if utils.DEBUG_TURN_PROFILE else 0
    _infer_from_grid_fast(bot, ct, nearby_entities, nearby_cache)
    if infer_start:
        utils.bump_profile(bot, "perception_infer_ns", time.time_ns() - infer_start)


def _infer_from_grid_fast(bot, ct: Controller, nearby_units, nearby_cache):
    """Lightweight inference for fast-scan path (assault bots). Re-reads from
    grid but only covers the small fast-scan visible set (~25 tiles)."""
    my_team = ct.get_team()
    known_obstacles = bot.pathfinding_state["known_obstacles"]
    visible_positions = getattr(bot, "visible_positions", set())
    round_now = ct.get_current_round()
    grid = bot.grid
    bot.visible_enemy_targets = []
    bot.visible_enemy_passable_buildings = set()
    bot.visible_friendly_builders = []

    bot.bot_locations.clear()
    for uid in nearby_units:
        entity_info = nearby_cache.get(uid)
        if entity_info is None:
            continue
        if entity_info["type"] != EntityType.BUILDER_BOT:
            continue
        if entity_info["team"] != my_team:
            continue
        p = entity_info["pos"]
        bot.bot_locations.add((p.x, p.y))
        bot.visible_friendly_builders.append((uid, p))
    current_pos = ct.get_position()
    bot.bot_locations.add((current_pos.x, current_pos.y))
    bot.visible_friendly_builders.append((ct.get_id(), current_pos))

    _HARVESTER = EntityType.HARVESTER
    _CORE = EntityType.CORE
    _passable = PASSABLE_ENTITIES
    ti_locs = bot.titanium_locations
    ax_locs = bot.axionite_locations

    for x, y in visible_positions:
        tile_key = (x, y)
        data = grid.get(tile_key, {})
        env = data.get("env")
        entity = data.get("entity")
        building = data.get("building")

        if env is Environment.ORE_TITANIUM:
            ti_locs.add(Position(x, y))
        elif env is Environment.ORE_AXIONITE:
            ax_locs.add(Position(x, y))
        else:
            pos = Position(x, y)
            ti_locs.discard(pos)
            ax_locs.discard(pos)

        harvester_present = entity is _HARVESTER or building is _HARVESTER
        is_obstacle = (
            env is Environment.WALL
            or env is Environment.ORE_TITANIUM
            or env is Environment.ORE_AXIONITE
            or harvester_present
        )
        if not is_obstacle:
            if entity is _CORE and data.get("entity_team") != my_team:
                is_obstacle = True
            elif entity is not None and entity not in _passable:
                is_obstacle = True
            if building is not None and building not in _passable:
                is_obstacle = True
            if building is _CORE and data.get("building_team") != my_team:
                is_obstacle = True

        if is_obstacle:
            known_obstacles.add(tile_key)
        else:
            known_obstacles.discard(tile_key)

        entity_team = data.get("entity_team")
        building_team = data.get("building_team")
        hostile_kind = None
        if entity is not None and entity_team is not None and entity_team != my_team:
            hostile_kind = entity
        elif building is not None and building_team is not None and building_team != my_team:
            hostile_kind = building

        if hostile_kind is not None:
            hostile_pos = Position(x, y)
            if hostile_kind is _CORE:
                bot.last_enemy_core_position = hostile_pos
                bot.enemy_core_anchor = hostile_pos
                bot.enemy_core_exact = True
            bot.visible_enemy_targets.append(
                assault.VisibleEnemy(
                    position=hostile_pos,
                    entity_type=hostile_kind,
                    direction=data.get("building_dir"),
                )
            )
            if hostile_kind is _HARVESTER:
                bot.confirmed_enemy_harvesters[tile_key] = round_now

            # Economy builders treat tiles near enemy sentinels/gunners as
            # temporary obstacles to avoid walking into fire zones.
            if (
                hostile_kind in (EntityType.SENTINEL, EntityType.GUNNER)
                and not getattr(bot, "is_assault_role", False)
            ):
                _DANGER_TTL = 8
                temp_obs = bot.pathfinding_state.setdefault("temporary_obstacles", {})
                danger_expiry = round_now + _DANGER_TTL
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        danger_key = (x + dx, y + dy)
                        temp_obs[danger_key] = max(
                            temp_obs.get(danger_key, -1),
                            danger_expiry,
                        )

    _update_harvester_tracking(bot, ct, my_team)


def _update_exploration_chunks(bot, ct: Controller, visible_tiles):
    """Updates chunk-based fog of war.  Deduplicates chunk writes by
    collecting unique touched chunks first."""
    utils.bump_profile(bot, "perception_chunk_update_calls")
    current_round = ct.get_current_round()
    current_pos = ct.get_position()
    _cs = CHUNK_SIZE
    touched = {(current_pos.x // _cs, current_pos.y // _cs)}
    for pos, _, _, _ in visible_tiles:
        touched.add((pos.x // _cs, pos.y // _cs))
    explored = bot.explored_tiles
    last_seen = bot.explored_chunk_last_seen
    for chunk in touched:
        explored.add(chunk)
        last_seen[chunk] = current_round


_CLEAR_DYNAMIC = {
    "entity": None, "entity_team": None, "id": None,
    "building": None, "building_team": None, "building_id": None,
    "building_hp": None, "building_max_hp": None,
    "building_dir": None, "bridge_target": None,
}
_CONVEYOR_ET = EntityType.CONVEYOR
_SPLITTER_ET = EntityType.SPLITTER
_ARMOURED_CONVEYOR_ET = EntityType.ARMOURED_CONVEYOR
_BRIDGE_ET = EntityType.BRIDGE


def _update_master_grid(bot, ct: Controller, visible_tiles, nearby_units, nearby_cache):
    """Writes raw vision data into the single source of truth."""
    utils.bump_profile(bot, "perception_grid_update_calls")
    current_round = ct.get_current_round()
    grid = bot.grid
    _clear = _CLEAR_DYNAMIC
    _HARVESTER = EntityType.HARVESTER
    # Incremental harvester tracking (R2).
    tracked_harvesters = getattr(bot, "tracked_harvesters", None)
    if tracked_harvesters is None:
        tracked_harvesters = {}
        bot.tracked_harvesters = tracked_harvesters

    visible_positions = set()
    visible_positions_add = visible_positions.add
    for pos, env, building_id, builder_bot_id in visible_tiles:
        pos_tuple = (pos.x, pos.y)
        visible_positions_add(pos_tuple)

        tile_data = grid.get(pos_tuple)
        _note_known_env_tile(bot, tile_data, env)
        if tile_data is None:
            tile_data = {}
            grid[pos_tuple] = tile_data
        else:
            old_b = tile_data.get("building")
            old_e = tile_data.get("entity")
            if old_b is _HARVESTER or old_e is _HARVESTER:
                tracked_harvesters.pop(pos_tuple, None)

        tile_data.update(_clear)
        tile_data["env"] = env
        tile_data["last_seen"] = current_round

        if builder_bot_id is not None:
            builder_info = nearby_cache[builder_bot_id]
            tile_data["id"] = builder_bot_id
            tile_data["entity"] = builder_info["type"]
            tile_data["entity_team"] = builder_info["team"]

        if building_id is None:
            continue

        building_info = nearby_cache[building_id]
        b_type = building_info["type"]
        tile_data["building"] = b_type
        tile_data["building_team"] = building_info["team"]
        tile_data["building_id"] = building_info.get("id")
        tile_data["building_hp"] = building_info.get("hp")
        tile_data["building_max_hp"] = building_info.get("max_hp")
        if b_type is _CONVEYOR_ET or b_type is _SPLITTER_ET or b_type is _ARMOURED_CONVEYOR_ET:
            tile_data["building_dir"] = building_info.get("direction")
        elif b_type is _BRIDGE_ET:
            tile_data["bridge_target"] = building_info.get("bridge_target")
        if b_type is _HARVESTER:
            tracked_harvesters[pos_tuple] = building_info["team"]

    for entity_id in nearby_units:
        entity_info = nearby_cache.get(entity_id)
        if entity_info is None:
            continue
        upos = entity_info["pos"]
        upos_tuple = (upos.x, upos.y)
        visible_positions_add(upos_tuple)
        tile_data = grid.get(upos_tuple)
        if tile_data is None:
            tile_data = {}
            grid[upos_tuple] = tile_data
        tile_data["id"] = entity_id
        tile_data["entity"] = entity_info["type"]
        tile_data["entity_team"] = entity_info["team"]
        tile_data["last_seen"] = current_round

    bot.visible_positions = visible_positions


def _infer_state_from_grid(
    bot,
    ct: Controller,
    nearby_units,
    nearby_cache,
    *,
    refresh_connected: bool = True,
):
    """Incrementally updates inferred state from currently visible tiles."""
    utils.bump_profile(bot, "perception_infer_calls")
    my_team = ct.get_team()
    known_obstacles = bot.pathfinding_state["known_obstacles"]
    visible_positions = getattr(bot, "visible_positions", set())
    topology_dirty = False
    round_now = ct.get_current_round()
    bot.visible_enemy_targets = []
    bot.visible_enemy_passable_buildings = set()
    bot.visible_friendly_builders = []
    visible_enemy_core_center = None

    bot.bot_locations.clear()
    for uid in nearby_units:
        entity_info = nearby_cache.get(uid)
        if entity_info is None:
            continue
        if entity_info["type"] != EntityType.BUILDER_BOT:
            continue
        if entity_info["team"] != my_team:
            continue
        p = entity_info["pos"]
        bot.bot_locations.add((p.x, p.y))
        bot.visible_friendly_builders.append((uid, p))
    current_pos = ct.get_position()
    bot.bot_locations.add((current_pos.x, current_pos.y))
    bot.visible_friendly_builders.append((ct.get_id(), current_pos))

    grid = bot.grid
    _WALL = Environment.WALL
    _ORE_TI = Environment.ORE_TITANIUM
    _ORE_AX = Environment.ORE_AXIONITE
    _HARVESTER_I = EntityType.HARVESTER
    _CORE_I = EntityType.CORE
    _passable = PASSABLE_ENTITIES
    ti_locs = bot.titanium_locations
    ax_locs = bot.axionite_locations

    for x, y in visible_positions:
        tile_key = (x, y)
        data = grid.get(tile_key, {})
        env = data.get("env")
        entity = data.get("entity")
        building = data.get("building")

        harvester_present = entity is _HARVESTER_I or building is _HARVESTER_I
        if env is _ORE_TI:
            ti_locs.add(Position(x, y))
        elif env is _ORE_AX:
            ax_locs.add(Position(x, y))
        else:
            pos = Position(x, y)
            ti_locs.discard(pos)
            ax_locs.discard(pos)

        is_obstacle = (
            env is _WALL or env is _ORE_TI or env is _ORE_AX
            or harvester_present
        )
        if not is_obstacle:
            entity_team = data.get("entity_team")
            if entity is _CORE_I and entity_team != my_team:
                is_obstacle = True
            elif entity is not None and entity not in _passable:
                is_obstacle = True
            if building is not None and building not in _passable:
                is_obstacle = True
            if building is _CORE_I and data.get("building_team") != my_team:
                is_obstacle = True

        if is_obstacle:
            known_obstacles.add(tile_key)
        else:
            known_obstacles.discard(tile_key)

        entity_team = data.get("entity_team")
        building_team = data.get("building_team")
        hostile_kind = None
        hostile_direction = None
        if entity is not None and entity_team is not None and entity_team != my_team:
            hostile_kind = entity
        elif building is not None and building_team is not None and building_team != my_team:
            hostile_kind = building
            hostile_direction = data.get("building_dir")

        if hostile_kind is not None:
            hostile_pos = Position(x, y)
            if hostile_kind is _CORE_I:
                visible_enemy_core_center = hostile_pos
            else:
                bot.visible_enemy_targets.append(
                    assault.VisibleEnemy(
                        position=hostile_pos,
                        entity_type=hostile_kind,
                        direction=hostile_direction,
                    )
                )
            if hostile_kind is _CONVEYOR_ET or hostile_kind is _SPLITTER_ET or hostile_kind is _ARMOURED_CONVEYOR_ET:
                bot.visible_enemy_passable_buildings.add(tile_key)
            if hostile_kind is _HARVESTER_I:
                bot.confirmed_enemy_harvesters[tile_key] = round_now
                if bot.harvester_anchor == hostile_pos:
                    bot.harvester_anchor_last_seen_round = round_now

        was_known_conveyor = tile_key in bot.known_friendly_conveyors
        is_friendly_conveyor = (
            (
                building is _CONVEYOR_ET
                or building is _SPLITTER_ET
                or building is _ARMOURED_CONVEYOR_ET
                or building is _BRIDGE_ET
            )
            and building_team == my_team
        )
        if is_friendly_conveyor and not was_known_conveyor:
            bot.known_friendly_conveyors.add(tile_key)
            topology_dirty = True
        elif not is_friendly_conveyor and was_known_conveyor:
            bot.known_friendly_conveyors.discard(tile_key)
            topology_dirty = True

    if visible_enemy_core_center is not None:
        bot.visible_enemy_targets.append(
            assault.VisibleEnemy(
                position=visible_enemy_core_center,
                entity_type=EntityType.CORE,
            )
        )
        bot.last_enemy_core_position = visible_enemy_core_center
        bot.enemy_core_anchor = visible_enemy_core_center
        bot.enemy_core_exact = True

    if refresh_connected and (
        topology_dirty or (round_now - bot.last_connected_refresh_round) >= 30
    ):
        # Recomputing "connected to core" is more expensive than just noticing a
        # friendly conveyor, so it is refreshed only when topology changes or on
        # a periodic heartbeat.
        friendly_conveyor_dirs: dict[tuple[int, int], object] = {}
        friendly_bridges: dict[tuple[int, int], tuple[int, int]] = {}
        stale_positions = []

        for key in bot.known_friendly_conveyors:
            data = bot.grid.get(key)
            if not data:
                stale_positions.append(key)
                continue

            building = data.get("building")
            team = data.get("building_team")
            if team != my_team:
                stale_positions.append(key)
                continue

            if building in {EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.ARMOURED_CONVEYOR}:
                build_dir = data.get("building_dir")
                if build_dir is None:
                    stale_positions.append(key)
                    continue
                friendly_conveyor_dirs[key] = build_dir
            elif building == EntityType.BRIDGE:
                bridge_target = data.get("bridge_target")
                if bridge_target is None:
                    stale_positions.append(key)
                    continue
                friendly_bridges[key] = (bridge_target.x, bridge_target.y)
            else:
                stale_positions.append(key)

        for key in stale_positions:
            bot.known_friendly_conveyors.discard(key)

        utils.bump_profile(bot, "perception_connected_refreshes")
        utils.max_profile(
            bot,
            "perception_known_friendly_conveyors_peak",
            len(bot.known_friendly_conveyors),
        )
        connected_start = time.time_ns() if utils.DEBUG_TURN_PROFILE else 0
        _update_connected_friendly_conveyors(
            bot, my_team, friendly_conveyor_dirs, friendly_bridges
        )
        if connected_start:
            utils.bump_profile(bot, "perception_connected_ns", time.time_ns() - connected_start)
        bot.last_connected_refresh_round = round_now

    utils.max_profile(bot, "perception_visible_enemy_targets_peak", len(bot.visible_enemy_targets))
    utils.max_profile(
        bot,
        "perception_visible_passable_enemy_buildings_peak",
        len(bot.visible_enemy_passable_buildings),
    )
    utils.max_profile(
        bot,
        "perception_visible_friendly_builders_peak",
        len(bot.visible_friendly_builders),
    )
    harvester_start = time.time_ns() if utils.DEBUG_TURN_PROFILE else 0
    _update_harvester_tracking(bot, ct, my_team)
    if harvester_start:
        utils.bump_profile(bot, "perception_harvester_tracking_ns", time.time_ns() - harvester_start)
    utils.max_profile(bot, "perception_known_harvesters_peak", len(bot.known_harvesters))


def _scan_nearby_markers(bot, ct: Controller, nearby_buildings, nearby_cache):
    utils.bump_profile(bot, "perception_marker_scan_calls")
    utils.max_profile(bot, "perception_marker_buildings_peak", len(nearby_buildings))
    bot.claimed_explore_chunks.clear()
    bot.claimed_assault_anchor_keys.clear()
    if hasattr(bot, "claimed_pipeline_positions"):
        bot.claimed_pipeline_positions.clear()
    chunk_cols = (ct.get_map_width() + CHUNK_SIZE - 1) // CHUNK_SIZE
    chunk_rows = (ct.get_map_height() + CHUNK_SIZE - 1) // CHUNK_SIZE
    map_width = ct.get_map_width()
    map_height = ct.get_map_height()
    current_round = ct.get_current_round()
    my_team = ct.get_team()
    my_owner_tag = marker.assault_claim_owner_tag(ct.get_id())
    marker_type_mask = (1 << marker.TYPE_BITS) - 1
    # parse_exploration_frontier_marker and OFFENSIVE_ROUTE don't exist in the
    # current marker module — skip the getattr probes entirely.

    for id in nearby_buildings:
        entity_info = nearby_cache.get(id)
        if entity_info is None:
            continue
        if entity_info["type"] != EntityType.MARKER or entity_info["team"] != my_team:
            continue
        utils.bump_profile(bot, "perception_markers_seen")

        marker_value = entity_info.get("marker_value")
        if marker_value is None:
            utils.bump_profile(bot, "perception_marker_value_reads")
            marker_value = ct.get_marker_value(id)
            entity_info["marker_value"] = marker_value

        # Fast precheck: world orientation markers have magic 0xD in top nibble.
        # Skip the full parse for the majority of markers that don't match.
        orientation = None
        if (marker_value >> 28) == 0xD:
            orientation = marker.parse_world_orientation_marker(marker_value)
        if orientation is not None:
            symmetry, confidence, rejected_mask, salient_flags = orientation
            bot.world_orientation = {
                "symmetry": symmetry,
                "confidence": confidence,
                "rejected_mask": rejected_mask,
                "salient_flags": salient_flags,
                "round_mod": current_round,
            }
            continue

        try:
            marker_type = marker.MarkerType(marker_value & marker_type_mask)
        except ValueError:
            marker_type = None

        if marker_type == marker.MarkerType.ASSAULT_CLAIM:
            assault_claim = marker.parse_assault_claim_marker(
                marker_value,
                map_width,
                map_height,
            )
            if assault_claim is not None:
                anchor_pos, owner_tag, claim_round = assault_claim
                if owner_tag != my_owner_tag and marker.is_recent_round(
                    claim_round,
                    current_round,
                    ASSAULT_CLAIM_TTL,
                ):
                    bot.claimed_assault_anchor_keys.add((anchor_pos.x, anchor_pos.y))
            continue

        if marker_type == marker.MarkerType.EXPLORE_CLAIM:
            claim = marker.parse_explore_claim_marker(marker_value, chunk_cols, chunk_rows)
            if claim is not None:
                claimed_chunk, _, claim_round = claim
                if marker.is_recent_round(claim_round, current_round, EXPLORE_CLAIM_TTL):
                    bot.claimed_explore_chunks.add(claimed_chunk)
            continue

        if marker_type == marker.MarkerType.ORE_LOCATION:
            ore_report = marker.parse_ore_marker(marker_value, map_width, map_height)
            if ore_report is not None:
                ore_pos, ore_round = ore_report
                if marker.is_recent_round(ore_round, current_round, ORE_MARKER_TTL):
                    bot.titanium_locations.add(ore_pos)
                    bot.pathfinding_state["known_obstacles"].add((ore_pos.x, ore_pos.y))
            continue

        if marker_type == marker.MarkerType.CONNECTED_CONVEYOR:
            conveyor_report = marker.parse_connected_conveyor_marker(
                marker_value, map_width, map_height
            )
            if conveyor_report is not None:
                conveyor_pos, conveyor_round = conveyor_report
                if marker.is_recent_round(conveyor_round, current_round, REMOTE_CACHE_TTL):
                    conveyor_tuple = (conveyor_pos.x, conveyor_pos.y)
                    bot.known_friendly_conveyors.add(conveyor_tuple)
                    bot.connected_friendly_conveyors.setdefault(conveyor_tuple, 0)
            continue

        if marker_type == marker.MarkerType.PIPELINE_CLAIM:
            claim_report = marker.parse_pipeline_claim_marker(
                marker_value, map_width, map_height
            )
            if claim_report is not None:
                claim_pos, claim_round = claim_report
                if marker.is_recent_round(
                    claim_round,
                    current_round,
                    PIPELINE_CLAIM_TTL,
                ):
                    if hasattr(bot, "claimed_pipeline_positions"):
                        bot.claimed_pipeline_positions.add((claim_pos.x, claim_pos.y))
            continue


def _update_connected_friendly_conveyors(
    bot,
    my_team,
    friendly_conveyor_dirs,
    friendly_bridges,
):
    """Tracks every remembered friendly conveyor that can feed into the core."""
    utils.max_profile(bot, "perception_connected_direction_sources_peak", len(friendly_conveyor_dirs))
    utils.max_profile(bot, "perception_connected_bridge_sources_peak", len(friendly_bridges))
    if bot.core_pos is None or (not friendly_conveyor_dirs and not friendly_bridges):
        bot.connected_friendly_conveyors = {}
        return

    core_x = bot.core_pos.x
    core_y = bot.core_pos.y
    reverse_links: dict[tuple[int, int], list[tuple[int, int]]] = {}
    connected: set[tuple[int, int]] = set()
    frontier: list[tuple[int, int]] = []
    forward_links: dict[tuple[int, int], tuple[int, int] | None] = {}

    for (x, y), build_dir in friendly_conveyor_dirs.items():
        pos_tuple = (x, y)
        if build_dir is not None:
            dx, dy = build_dir.delta()
            next_tuple = (x + dx, y + dy)
        else:
            next_tuple = None

        if (
            next_tuple is not None
            and (next_tuple[0] - core_x) ** 2 + (next_tuple[1] - core_y) ** 2 <= 2
        ):
            connected.add(pos_tuple)
            frontier.append(pos_tuple)

        if next_tuple is None:
            continue

        forward_links[pos_tuple] = next_tuple
        reverse_links.setdefault(next_tuple, []).append(pos_tuple)

    # 2. Map Bridge Links
    for (sx, sy), target_tuple in friendly_bridges.items():
        start_tuple = (sx, sy)

        # If the bridge shoots items directly to the core area
        if (target_tuple[0] - core_x) ** 2 + (target_tuple[1] - core_y) ** 2 <= 2:
            connected.add(start_tuple)
            frontier.append(start_tuple)

        # Link backward: if the bridge's target is connected, the bridge's start is connected
        forward_links[start_tuple] = target_tuple
        reverse_links.setdefault(target_tuple, []).append(start_tuple)

    while frontier:
        current = frontier.pop()
        for prev in reverse_links.get(current, ()):
            if prev in connected:
                continue
            connected.add(prev)
            frontier.append(prev)

    connected_counts = {pos_tuple: 0 for pos_tuple in connected}
    tracked = getattr(bot, "tracked_harvesters", {})
    for harvester_tuple, h_team in tracked.items():
        if h_team != my_team:
            continue
        adjacent_connected: set[tuple[int, int]] = set()
        hx, hy = harvester_tuple
        for dx, dy in _CARDINAL_DELTAS:
            neighbor_tuple = (hx + dx, hy + dy)
            if neighbor_tuple in connected_counts:
                adjacent_connected.add(neighbor_tuple)

        for start_tuple in adjacent_connected:
            current = start_tuple
            visited: set[tuple[int, int]] = set()
            while current in connected_counts and current not in visited:
                connected_counts[current] += 1
                visited.add(current)
                next_tuple = forward_links.get(current)
                if next_tuple not in connected_counts:
                    break
                current = next_tuple

    effective_loads: dict[tuple[int, int], int] = {}

    def downstream_peak_load(pos_tuple: tuple[int, int]) -> int:
        cached = effective_loads.get(pos_tuple)
        if cached is not None:
            return cached

        local_load = connected_counts.get(pos_tuple, 0)
        next_tuple = forward_links.get(pos_tuple)
        if next_tuple in connected_counts:
            local_load = max(local_load, downstream_peak_load(next_tuple))

        effective_loads[pos_tuple] = local_load
        return local_load

    for pos_tuple in connected_counts:
        downstream_peak_load(pos_tuple)

    utils.max_profile(bot, "perception_connected_conveyors_peak", len(effective_loads))
    bot.connected_friendly_conveyors = effective_loads


def _update_harvester_tracking(bot, ct: Controller, my_team) -> None:
    utils.bump_profile(bot, "perception_harvester_tracking_calls")
    # Use incrementally-maintained tracked_harvesters instead of scanning
    # the entire grid.
    all_harvesters = getattr(bot, "tracked_harvesters", {})

    for harvester_pos, owner_team in all_harvesters.items():
        if harvester_pos not in bot.known_harvesters:
            bot.known_harvesters[harvester_pos] = {
                "team": owner_team,
                "adjacent_conveyors": 0,
            }

        adjacent_count = _count_adjacent_conveyors(bot, ct, harvester_pos, my_team=my_team)
        info = bot.known_harvesters[harvester_pos]
        old_count = info.get("adjacent_conveyors", 0)
        info["adjacent_conveyors"] = adjacent_count
        # Track peak adjacent conveyors so retile logic can distinguish
        # "was connected, route destroyed" from "never connected yet".
        if adjacent_count > info.get("prev_adjacent_conveyors", 0):
            info["prev_adjacent_conveyors"] = adjacent_count

        if owner_team == my_team and adjacent_count > 0:
            bot.claimed_harvesters.add(harvester_pos)
        elif owner_team == my_team and adjacent_count == 0:
            bot.claimed_harvesters.discard(harvester_pos)

    stale = [pos for pos in bot.known_harvesters if pos not in all_harvesters]
    for pos in stale:
        del bot.known_harvesters[pos]
        bot.claimed_harvesters.discard(pos)
    utils.max_profile(bot, "perception_claimed_harvesters_peak", len(bot.claimed_harvesters))
