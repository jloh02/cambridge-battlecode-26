from cambc import (
    Controller,
    EntityType,
    Environment,
    GameConstants,
    Position,
)
import math
import assault
import marker
import utils

MAX_VISION_ASSUMPTION = math.sqrt(GameConstants.BUILDER_BOT_VISION_RADIUS_SQ) - 1
CHUNK_SIZE = max(1, int(MAX_VISION_ASSUMPTION))
EXPLORE_CLAIM_TTL = 20
REMOTE_CACHE_TTL = 80
ORE_MARKER_TTL = 120
FAST_SCAN_RADIUS_SQ = 9

# Entities that do not block movement
PASSABLE_ENTITIES = {
    EntityType.ROAD,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.MARKER,
    EntityType.CORE,
    EntityType.BUILDER_BOT,
}


def _friendly_harvester_positions(bot, my_team) -> list[tuple[int, int]]:
    harvesters = []
    for key, data in bot.grid.items():
        if data.get("building") == EntityType.HARVESTER and data.get("building_team") == my_team:
            harvesters.append(key)
            continue
        if data.get("entity") == EntityType.HARVESTER and data.get("entity_team") == my_team:
            harvesters.append(key)
    return harvesters


def _connected_friendly_harvester_positions(bot, my_team) -> set[tuple[int, int]]:
    connected = set()
    connected_conveyors = set(bot.connected_friendly_conveyors)
    if not connected_conveyors:
        return connected

    for hx, hy in _friendly_harvester_positions(bot, my_team):
        for direction in utils.CARDINAL_DIRECTIONS:
            dx, dy = direction.delta()
            if (hx + dx, hy + dy) in connected_conveyors:
                connected.add((hx, hy))
                break
    return connected


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


def _collect_visible_snapshot(ct: Controller, nearby_tiles):
    """Same strategy as `jon-5`, cheaper execution: build buildings from tiles and units from the unit list."""
    get_tile_builder_bot_id = getattr(ct, "get_tile_builder_bot_id", None)
    entity_type_cache: dict[int, EntityType] = {}
    entity_team_cache: dict[int, object] = {}
    visible_tiles: list[tuple[Position, Environment, int | None, int | None]] = []
    nearby_buildings: list[int] = []
    nearby_units: list[int] = []
    nearby_cache: dict[int, dict] = {}

    def cached_entity_type(entity_id: int) -> EntityType:
        entity_type = entity_type_cache.get(entity_id)
        if entity_type is None:
            entity_type = ct.get_entity_type(entity_id)
            entity_type_cache[entity_id] = entity_type
        return entity_type

    def cached_entity_team(entity_id: int):
        entity_team = entity_team_cache.get(entity_id)
        if entity_team is None:
            entity_team = ct.get_team(entity_id)
            entity_team_cache[entity_id] = entity_team
        return entity_team

    for pos in nearby_tiles:
        env = ct.get_tile_env(pos)
        building_id = ct.get_tile_building_id(pos)
        builder_bot_id = (
            get_tile_builder_bot_id(pos) if get_tile_builder_bot_id is not None else None
        )
        visible_tiles.append((pos, env, building_id, builder_bot_id))

        if building_id is not None:
            b_type = cached_entity_type(building_id)
            building_info = {
                "pos": pos,
                "type": b_type,
                "team": cached_entity_team(building_id),
            }
            if b_type in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}:
                building_info["direction"] = ct.get_direction(building_id)
            elif b_type == EntityType.BRIDGE:
                building_info["bridge_target"] = ct.get_bridge_target(building_id)
            nearby_cache[building_id] = building_info
            nearby_buildings.append(building_id)

        if builder_bot_id is not None:
            nearby_cache[builder_bot_id] = {
                "pos": pos,
                "type": EntityType.BUILDER_BOT,
                "team": cached_entity_team(builder_bot_id),
            }
            nearby_units.append(builder_bot_id)

    # `jon-5o` keeps the tile-driven building snapshot, but nearby non-builder
    # units still need the dedicated SDK query because tiles only expose
    # builder-bot occupancy directly.
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

    return visible_tiles, nearby_buildings, nearby_units, nearby_cache


def scan_around(bot, ct: Controller, *, fast: bool = False):
    """Main perception entry point.

    The order matters: first refresh the coarse exploration view, then write
    raw observations into the remembered grid, then decode marker hints, and
    only after that rebuild the derived state used by the current mode.
    """
    if fast:
        # `jon-5o` departure from `jon-5`: stable tiling turns only refresh a
        # tight local window, then rely on the existing remembered map for the
        # rest. This preserves the same route-building policy with fewer
        # controller calls in the steady state.
        _scan_local_fast(bot, ct)
        return

    nearby_tiles = _get_nearby_tiles(bot, ct)
    visible_tiles, nearby_buildings, nearby_units, nearby_cache = (
        _collect_visible_snapshot(ct, nearby_tiles)
    )

    _update_exploration_chunks(bot, ct, visible_tiles)
    _update_master_grid(bot, ct, visible_tiles, nearby_units, nearby_cache)
    _scan_nearby_markers(bot, ct, nearby_buildings, nearby_cache)
    _infer_state_from_grid(bot, ct, nearby_units, nearby_cache)


def _scan_local_fast(bot, ct: Controller):
    nearby_tiles = _get_nearby_tiles(bot, ct, FAST_SCAN_RADIUS_SQ)
    current_round = ct.get_current_round()
    visible_positions = set()
    nearby_entities = []
    nearby_cache = {}
    bot.bot_locations.clear()
    bot.bot_locations.add((ct.get_position().x, ct.get_position().y))
    get_tile_builder_bot_id = getattr(ct, "get_tile_builder_bot_id", None)
    my_team = ct.get_team()

    for pos in nearby_tiles:
        pos_tuple = (pos.x, pos.y)
        visible_positions.add(pos_tuple)
        tile_data = bot.grid.setdefault(pos_tuple, {})
        tile_data["env"] = ct.get_tile_env(pos)
        tile_data["last_seen"] = current_round

        # Clear dynamic state on visible tiles so the remembered grid stays
        # locally accurate even when we skip the full nearby-entity scan.
        tile_data["entity"] = None
        tile_data["entity_team"] = None
        tile_data["id"] = None
        tile_data["building"] = None
        tile_data["building_team"] = None
        tile_data["building_dir"] = None
        tile_data["bridge_target"] = None

        building_id = ct.get_tile_building_id(pos)
        if building_id is not None:
            b_type = ct.get_entity_type(building_id)
            tile_data["building"] = b_type
            tile_data["building_team"] = ct.get_team(building_id)
            if b_type in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}:
                tile_data["building_dir"] = ct.get_direction(building_id)
            elif b_type == EntityType.BRIDGE:
                tile_data["bridge_target"] = ct.get_bridge_target(building_id)

        if get_tile_builder_bot_id is None:
            continue

        builder_bot_id = get_tile_builder_bot_id(pos)
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

    bot.visible_positions = visible_positions
    _infer_state_from_grid(
        bot, ct, nearby_entities, nearby_cache, refresh_connected=False
    )


def _update_exploration_chunks(bot, ct: Controller, visible_tiles):
    """Updates chunk-based fog of war."""
    current_round = ct.get_current_round()
    current_pos = ct.get_position()
    current_chunk = (current_pos.x // CHUNK_SIZE, current_pos.y // CHUNK_SIZE)
    bot.explored_tiles.add(current_chunk)
    bot.explored_chunk_last_seen[current_chunk] = current_round

    for pos, _, _, _ in visible_tiles:
        chunk = (pos.x // CHUNK_SIZE, pos.y // CHUNK_SIZE)
        bot.explored_tiles.add(chunk)
        bot.explored_chunk_last_seen[chunk] = current_round


def _update_master_grid(bot, ct: Controller, visible_tiles, nearby_units, nearby_cache):
    """Writes raw vision data into the single source of truth.

    The grid is deliberately more primitive than the higher-level caches. It is
    the durable memory layer that later inference and pathfinding rebuild from.
    """
    current_round = ct.get_current_round()

    # Same strategy as `jon-5`, cheaper execution: populate the visible world
    # from one tile snapshot instead of a second pass of entity position lookups.
    visible_positions = set()
    for pos, env, building_id, builder_bot_id in visible_tiles:
        pos_tuple = (pos.x, pos.y)
        visible_positions.add(pos_tuple)
        if pos_tuple not in bot.grid:
            bot.grid[pos_tuple] = {}

        tile_data = bot.grid[pos_tuple]
        tile_data["env"] = env
        tile_data["last_seen"] = current_round

        # Clear dynamic entities on visible tiles so ghosts don't linger.
        tile_data["entity"] = None
        tile_data["entity_team"] = None
        tile_data["id"] = None
        tile_data["building"] = None
        tile_data["building_team"] = None
        tile_data["building_dir"] = None
        tile_data["bridge_target"] = None

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
        if b_type in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}:
            tile_data["building_dir"] = building_info.get("direction")
        elif b_type == EntityType.BRIDGE:
            tile_data["bridge_target"] = building_info.get("bridge_target")

    for entity_id in nearby_units:
        entity_info = nearby_cache.get(entity_id)
        if entity_info is None:
            continue

        pos = entity_info["pos"]
        pos_tuple = (pos.x, pos.y)
        visible_positions.add(pos_tuple)
        tile_data = bot.grid.setdefault(pos_tuple, {})
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
    my_team = ct.get_team()
    known_obstacles = bot.pathfinding_state["known_obstacles"]
    visible_positions = getattr(bot, "visible_positions", set())
    topology_dirty = False
    round_now = ct.get_current_round()
    bot.visible_enemy_targets = []
    bot.visible_enemy_passable_buildings = set()
    bot.visible_friendly_builders = []
    visible_enemy_core_center = None
    for entity_id in set(ct.get_nearby_entities()):
        if ct.get_entity_type(entity_id) != EntityType.CORE:
            continue
        if ct.get_team(entity_id) == my_team:
            continue
        visible_enemy_core_center = ct.get_position(entity_id)
        break

    bot.bot_locations.clear()
    for id in nearby_units:
        entity_info = nearby_cache.get(id)
        if entity_info is None:
            continue
        if entity_info["type"] != EntityType.BUILDER_BOT:
            continue
        if entity_info["team"] != my_team:
            continue
        p = entity_info["pos"]
        bot.bot_locations.add((p.x, p.y))
        bot.visible_friendly_builders.append((id, p))
    current_pos = ct.get_position()
    bot.bot_locations.add((current_pos.x, current_pos.y))
    bot.visible_friendly_builders.append((ct.get_id(), current_pos))

    for x, y in visible_positions:
        data = bot.grid.get((x, y), {})
        pos = Position(x, y)
        env = data.get("env")
        entity = data.get("entity")
        building = data.get("building")

        # --- 1. Ores ---
        harvester_present = (
            entity == EntityType.HARVESTER or building == EntityType.HARVESTER
        )
        if not harvester_present:
            if env == Environment.ORE_TITANIUM:
                bot.titanium_locations.add(pos)
            elif env == Environment.ORE_AXIONITE:
                bot.axionite_locations.add(pos)
            else:
                bot.titanium_locations.discard(pos)
                bot.axionite_locations.discard(pos)

        # --- 2. Obstacles ---
        is_obstacle = False

        if env in {
            Environment.WALL,
            Environment.ORE_TITANIUM,
            Environment.ORE_AXIONITE,
        }:
            is_obstacle = True

        if harvester_present:
            is_obstacle = True

            bot.titanium_locations.discard(pos)
            bot.axionite_locations.discard(pos)
        elif entity == EntityType.CORE and data.get("entity_team") != my_team:
            is_obstacle = True
        elif entity is not None and entity not in PASSABLE_ENTITIES:
            is_obstacle = True

        if building is not None and building not in PASSABLE_ENTITIES:
            is_obstacle = True

        if (
            building is not None
            and building == EntityType.CORE
            and data.get("building_team") != my_team
        ):
            is_obstacle = True

        if is_obstacle:
            known_obstacles.add((x, y))
        else:
            known_obstacles.discard((x, y))

        tile_key = (x, y)
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
            if hostile_kind != EntityType.CORE:
                bot.visible_enemy_targets.append(
                    assault.VisibleEnemy(
                        position=pos,
                        entity_type=hostile_kind,
                        direction=hostile_direction,
                    )
                )
            if hostile_kind in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}:
                bot.visible_enemy_passable_buildings.add(tile_key)
            if hostile_kind == EntityType.HARVESTER:
                bot.confirmed_enemy_harvesters[tile_key] = round_now
                if bot.harvester_anchor == pos:
                    bot.harvester_anchor_last_seen_round = round_now

        was_known_conveyor = tile_key in bot.known_friendly_conveyors
        is_friendly_conveyor = False
        if (
            building in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}
            and data.get("building_team") == my_team
        ):
            is_friendly_conveyor = True
        elif building == EntityType.BRIDGE and data.get("building_team") == my_team:
            is_friendly_conveyor = True

        if is_friendly_conveyor and not was_known_conveyor:
            bot.known_friendly_conveyors.add(tile_key)
            topology_dirty = True
        elif (not is_friendly_conveyor) and was_known_conveyor:
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
        topology_dirty or (round_now - bot.last_connected_refresh_round) >= 15
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

            if building in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}:
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

        _update_connected_friendly_conveyors(
            bot, my_team, friendly_conveyor_dirs, friendly_bridges
        )
        bot.last_connected_refresh_round = round_now

    for hx, hy in _connected_friendly_harvester_positions(bot, my_team):
        bot.known_connected_harvesters.add((hx, hy))


def _scan_nearby_markers(bot, ct: Controller, nearby_buildings, nearby_cache):
    bot.claimed_explore_chunks.clear()
    chunk_cols = (ct.get_map_width() + CHUNK_SIZE - 1) // CHUNK_SIZE
    chunk_rows = (ct.get_map_height() + CHUNK_SIZE - 1) // CHUNK_SIZE
    map_width = ct.get_map_width()
    map_height = ct.get_map_height()
    current_round = ct.get_current_round()
    my_team = ct.get_team()

    for id in nearby_buildings:
        entity_info = nearby_cache.get(id)
        if entity_info is None:
            continue
        if entity_info["type"] != EntityType.MARKER or entity_info["team"] != my_team:
            continue

        marker_value = entity_info.get("marker_value")
        if marker_value is None:
            marker_value = ct.get_marker_value(id)
            entity_info["marker_value"] = marker_value

        claim = marker.parse_explore_claim_marker(marker_value, chunk_cols, chunk_rows)
        if claim is None:
            ore_report = marker.parse_ore_marker(marker_value, map_width, map_height)
            if ore_report is not None:
                ore_pos, ore_round = ore_report
                if marker.is_recent_round(ore_round, current_round, ORE_MARKER_TTL):
                    bot.titanium_locations.add(ore_pos)
                    bot.pathfinding_state["known_obstacles"].add((ore_pos.x, ore_pos.y))
                continue

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

            harvester_report = marker.parse_connected_harvester_marker(
                marker_value, map_width, map_height
            )
            if harvester_report is None:
                continue

            harvester_pos, harvester_round = harvester_report
            if marker.is_recent_round(harvester_round, current_round, REMOTE_CACHE_TTL):
                bot.known_connected_harvesters.add((harvester_pos.x, harvester_pos.y))
            continue

        claimed_chunk, _, claim_round = claim
        if marker.is_recent_round(claim_round, current_round, EXPLORE_CLAIM_TTL):
            bot.claimed_explore_chunks.add(claimed_chunk)


def _update_connected_friendly_conveyors(
    bot,
    my_team,
    friendly_conveyor_dirs,
    friendly_bridges,
):
    """Tracks every remembered friendly conveyor that can feed into the core."""
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
    for harvester_tuple in _friendly_harvester_positions(bot, my_team):
        adjacent_connected: set[tuple[int, int]] = set()
        hx, hy = harvester_tuple
        for direction in utils.CARDINAL_DIRECTIONS:
            dx, dy = direction.delta()
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

    bot.connected_friendly_conveyors = effective_loads
