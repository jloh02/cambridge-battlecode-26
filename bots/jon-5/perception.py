from cambc import (
    Controller,
    EntityType,
    Environment,
    GameConstants,
    Position,
)
import math
import marker

MAX_VISION_ASSUMPTION = math.sqrt(GameConstants.BUILDER_BOT_VISION_RADIUS_SQ) - 1
CHUNK_SIZE = max(1, int(MAX_VISION_ASSUMPTION))
EXPLORE_CLAIM_TTL = 20
REMOTE_CACHE_TTL = 80
ORE_MARKER_TTL = 120

# Entities that do not block movement
PASSABLE_ENTITIES = {
    EntityType.ROAD,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.MARKER,
    EntityType.CORE,
    EntityType.BUILDER_BOT,
}


def scan_around(bot, ct: Controller):
    """Main perception entry point.

    The order matters: first refresh the coarse exploration view, then write
    raw observations into the remembered grid, then decode marker hints, and
    only after that rebuild the derived state used by the current mode.
    """
    nearby_tiles = list(ct.get_nearby_tiles())
    nearby_entities = list(ct.get_nearby_entities())
    nearby_buildings = list(ct.get_nearby_buildings())

    _update_exploration_chunks(bot, ct, nearby_tiles, nearby_buildings)
    _update_master_grid(bot, ct, nearby_tiles, nearby_entities, nearby_buildings)
    _scan_nearby_markers(bot, ct, nearby_entities)
    _infer_state_from_grid(bot, ct, nearby_entities)


def _update_exploration_chunks(bot, ct: Controller, nearby_tiles, nearby_buildings):
    """Updates chunk-based fog of war."""
    current_pos = ct.get_position()
    bot.explored_tiles.add((current_pos.x // CHUNK_SIZE, current_pos.y // CHUNK_SIZE))

    for pos in nearby_tiles:
        bot.explored_tiles.add((pos.x // CHUNK_SIZE, pos.y // CHUNK_SIZE))

    for id in nearby_buildings:
        if ct.get_team(id) == ct.get_team():
            p = ct.get_position(id)
            bot.explored_tiles.add((p.x // CHUNK_SIZE, p.y // CHUNK_SIZE))


def _update_master_grid(
    bot, ct: Controller, nearby_tiles, nearby_entities, nearby_buildings
):
    """Writes raw vision data into the single source of truth.

    The grid is deliberately more primitive than the higher-level caches. It is
    the durable memory layer that later inference and pathfinding rebuild from.
    """
    current_round = ct.get_current_round()

    # 1. Map Static Environment
    visible_positions = set()
    for pos in nearby_tiles:
        pos_tuple = (pos.x, pos.y)
        visible_positions.add(pos_tuple)
        if pos_tuple not in bot.grid:
            bot.grid[pos_tuple] = {}

        bot.grid[pos_tuple]["env"] = ct.get_tile_env(pos)
        bot.grid[pos_tuple]["last_seen"] = current_round

        # Clear dynamic entities on visible tiles so ghosts don't linger
        bot.grid[pos_tuple]["entity"] = None
        bot.grid[pos_tuple]["entity_team"] = None
        bot.grid[pos_tuple]["id"] = None
        bot.grid[pos_tuple]["building"] = None
        bot.grid[pos_tuple]["building_team"] = None
        bot.grid[pos_tuple]["building_dir"] = None

    # 2. Map Dynamic Entities
    for id in nearby_entities:
        pos = ct.get_position(id)
        pos_tuple = (pos.x, pos.y)
        visible_positions.add(pos_tuple)

        if pos_tuple not in bot.grid:
            bot.grid[pos_tuple] = {}

        bot.grid[pos_tuple]["id"] = id
        bot.grid[pos_tuple]["entity"] = ct.get_entity_type(id)
        bot.grid[pos_tuple]["entity_team"] = ct.get_team(id)
        bot.grid[pos_tuple]["last_seen"] = current_round

    # 3. Map Buildings
    for id in nearby_buildings:
        pos = ct.get_position(id)
        pos_tuple = (pos.x, pos.y)
        visible_positions.add(pos_tuple)

        if pos_tuple not in bot.grid:
            bot.grid[pos_tuple] = {}

        b_type = ct.get_entity_type(id)
        bot.grid[pos_tuple]["building"] = b_type
        bot.grid[pos_tuple]["building_team"] = ct.get_team(id)
        bot.grid[pos_tuple]["last_seen"] = current_round

        if b_type in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}:
            bot.grid[pos_tuple]["building_dir"] = ct.get_direction(id)
        elif b_type == EntityType.BRIDGE:
            bot.grid[pos_tuple]["bridge_target"] = ct.get_bridge_target(id)

    bot.visible_positions = visible_positions


def _infer_state_from_grid(bot, ct: Controller, nearby_entities):
    """Incrementally updates inferred state from currently visible tiles."""
    my_team = ct.get_team()
    known_obstacles = bot.pathfinding_state["known_obstacles"]
    visible_positions = getattr(bot, "visible_positions", set())
    topology_dirty = False

    bot.bot_locations.clear()
    for id in nearby_entities:
        if ct.get_entity_type(id) != EntityType.BUILDER_BOT:
            continue
        if ct.get_team(id) != my_team:
            continue
        p = ct.get_position(id)
        bot.bot_locations.add((p.x, p.y))

    for x, y in visible_positions:
        data = bot.grid.get((x, y), {})
        pos = Position(x, y)
        env = data.get("env")
        entity = data.get("entity")
        building = data.get("building")

        # --- 1. Ores ---
        if entity != EntityType.HARVESTER:
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

        if entity == EntityType.HARVESTER:
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

    round_now = ct.get_current_round()
    if topology_dirty or (round_now - bot.last_connected_refresh_round) >= 15:
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
            bot, friendly_conveyor_dirs, friendly_bridges
        )
        bot.last_connected_refresh_round = round_now


def _scan_nearby_markers(bot, ct: Controller, nearby_entities):
    bot.claimed_explore_chunks.clear()
    chunk_cols = (ct.get_map_width() + CHUNK_SIZE - 1) // CHUNK_SIZE
    chunk_rows = (ct.get_map_height() + CHUNK_SIZE - 1) // CHUNK_SIZE
    map_width = ct.get_map_width()
    map_height = ct.get_map_height()
    current_round = ct.get_current_round()
    my_team = ct.get_team()

    for id in nearby_entities:
        if ct.get_entity_type(id) != EntityType.MARKER or ct.get_team(id) != my_team:
            continue

        marker_value = ct.get_marker_value(id)

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
            if conveyor_report is None:
                continue

            conveyor_pos, conveyor_round = conveyor_report
            if marker.is_recent_round(conveyor_round, current_round, REMOTE_CACHE_TTL):
                conveyor_tuple = (conveyor_pos.x, conveyor_pos.y)
                bot.known_friendly_conveyors.add(conveyor_tuple)
                bot.connected_friendly_conveyors.add(conveyor_tuple)
            continue

        claimed_chunk, _, claim_round = claim
        if marker.is_recent_round(claim_round, current_round, EXPLORE_CLAIM_TTL):
            bot.claimed_explore_chunks.add(claimed_chunk)


def _update_connected_friendly_conveyors(bot, friendly_conveyor_dirs, friendly_bridges):
    """Marks every remembered friendly conveyor that can feed into the core."""
    if bot.core_pos is None or (not friendly_conveyor_dirs and not friendly_bridges):
        bot.connected_friendly_conveyors = set()
        return

    reverse_links: dict[tuple[int, int], list[tuple[int, int]]] = {}
    connected: set[tuple[int, int]] = set()
    frontier: list[tuple[int, int]] = []

    for (x, y), build_dir in friendly_conveyor_dirs.items():
        pos_tuple = (x, y)
        if (
            build_dir is not None
            and Position(x, y).add(build_dir).distance_squared(bot.core_pos) <= 2
        ):
            connected.add(pos_tuple)
            frontier.append(pos_tuple)

        if build_dir is None:
            continue

        next_pos = Position(x, y).add(build_dir)
        next_tuple = (next_pos.x, next_pos.y)
        reverse_links.setdefault(next_tuple, []).append(pos_tuple)

    # 2. Map Bridge Links
    for (sx, sy), target_tuple in friendly_bridges.items():
        start_tuple = (sx, sy)

        # If the bridge shoots items directly to the core area
        if (
            Position(target_tuple[0], target_tuple[1]).distance_squared(bot.core_pos)
            <= 2
        ):
            connected.add(start_tuple)
            frontier.append(start_tuple)

        # Link backward: if the bridge's target is connected, the bridge's start is connected
        reverse_links.setdefault(target_tuple, []).append(start_tuple)

    while frontier:
        current = frontier.pop()
        for prev in reverse_links.get(current, ()):
            if prev in connected:
                continue
            connected.add(prev)
            frontier.append(prev)

    bot.connected_friendly_conveyors = connected
