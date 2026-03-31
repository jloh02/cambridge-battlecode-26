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
    """Main perception entry point."""
    _update_exploration_chunks(bot, ct)
    _update_master_grid(bot, ct)
    _scan_nearby_markers(bot, ct)
    _infer_state_from_grid(bot, ct)


def _update_exploration_chunks(bot, ct: Controller):
    """Updates chunk-based fog of war."""
    current_pos = ct.get_position()
    bot.explored_tiles.add((current_pos.x // CHUNK_SIZE, current_pos.y // CHUNK_SIZE))

    for pos in ct.get_nearby_tiles():
        bot.explored_tiles.add((pos.x // CHUNK_SIZE, pos.y // CHUNK_SIZE))

    for id in ct.get_nearby_buildings():
        if ct.get_team(id) == ct.get_team():
            p = ct.get_position(id)
            bot.explored_tiles.add((p.x // CHUNK_SIZE, p.y // CHUNK_SIZE))


def _update_master_grid(bot, ct: Controller):
    """Writes raw vision data into the single source of truth."""
    current_round = ct.get_current_round()

    # 1. Map Static Environment
    for pos in ct.get_nearby_tiles():
        pos_tuple = (pos.x, pos.y)
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
    for id in ct.get_nearby_entities():
        pos = ct.get_position(id)
        pos_tuple = (pos.x, pos.y)

        if pos_tuple not in bot.grid:
            bot.grid[pos_tuple] = {}

        bot.grid[pos_tuple]["id"] = id
        bot.grid[pos_tuple]["entity"] = ct.get_entity_type(id)
        bot.grid[pos_tuple]["entity_team"] = ct.get_team(id)
        bot.grid[pos_tuple]["last_seen"] = current_round

    # 3. Map Buildings
    for id in ct.get_nearby_buildings():
        pos = ct.get_position(id)
        pos_tuple = (pos.x, pos.y)

        if pos_tuple not in bot.grid:
            bot.grid[pos_tuple] = {}

        b_type = ct.get_entity_type(id)
        bot.grid[pos_tuple]["building"] = b_type
        bot.grid[pos_tuple]["building_team"] = ct.get_team(id)
        bot.grid[pos_tuple]["last_seen"] = current_round

        if b_type in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}:
            bot.grid[pos_tuple]["building_dir"] = ct.get_direction(id)


def _infer_state_from_grid(bot, ct: Controller):
    """Parses the grid to generate lists needed for decision making and A*."""
    # Reset states for the current tick
    bot.bot_locations.clear()
    bot.known_friendly_conveyors.clear()
    bot.connected_friendly_conveyors.clear()

    my_team = ct.get_team()
    friendly_conveyor_dirs: dict[tuple[int, int], object] = {}

    for (x, y), data in bot.grid.items():
        pos = Position(x, y)
        env = data.get("env")
        entity = data.get("entity")
        building = data.get("building")

        # --- 1. Ores ---
        if entity != EntityType.HARVESTER:
            if env == Environment.ORE_TITANIUM:
                bot.titanium_locations.add(pos)
                bot.pathfinding_state["known_obstacles"].add(pos)
            elif env == Environment.ORE_AXIONITE:
                bot.axionite_locations.add(pos)
                bot.pathfinding_state["known_obstacles"].add(pos)

        # --- 2. Obstacles ---
        is_obstacle = False

        if env == Environment.WALL:
            is_obstacle = True

        if entity == EntityType.HARVESTER:
            is_obstacle = True

            # TODO check teams and maybe destroy enemy harvesters?
            bot.titanium_locations.discard(pos)
            bot.axionite_locations.discard(pos)
        elif entity == EntityType.CORE and data.get("entity_team") != my_team:
            is_obstacle = True
        elif entity is not None and entity not in PASSABLE_ENTITIES:
            is_obstacle = True

        if building is not None and building not in PASSABLE_ENTITIES:
            is_obstacle = True

        if is_obstacle:
            bot.pathfinding_state["known_obstacles"].add((x, y))
        else:
            bot.pathfinding_state["known_obstacles"].discard((x, y))

        # --- 3. Allies ---
        if entity == EntityType.BUILDER_BOT and data.get("entity_team") == my_team:
            bot.bot_locations.add((x, y))

        if (
            building in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}
            and data.get("building_team") == my_team
        ):
            bot.known_friendly_conveyors.add((x, y))
            friendly_conveyor_dirs[(x, y)] = data.get("building_dir")

    _update_connected_friendly_conveyors(bot, friendly_conveyor_dirs)


def _scan_nearby_markers(bot, ct: Controller):
    bot.claimed_explore_chunks.clear()
    chunk_cols = (ct.get_map_width() + CHUNK_SIZE - 1) // CHUNK_SIZE
    chunk_rows = (ct.get_map_height() + CHUNK_SIZE - 1) // CHUNK_SIZE
    current_round = ct.get_current_round()
    my_team = ct.get_team()

    for id in ct.get_nearby_entities():
        if ct.get_entity_type(id) != EntityType.MARKER or ct.get_team(id) != my_team:
            continue

        claim = marker.parse_explore_claim_marker(
            ct.get_marker_value(id), chunk_cols, chunk_rows
        )
        if claim is None:
            continue

        claimed_chunk, claim_round = claim
        if marker.is_recent_claim_round(claim_round, current_round, EXPLORE_CLAIM_TTL):
            bot.claimed_explore_chunks.add(claimed_chunk)


def _update_connected_friendly_conveyors(bot, friendly_conveyor_dirs):
    """Marks every remembered friendly conveyor that can feed into the core."""
    if bot.core_pos is None or not friendly_conveyor_dirs:
        return

    reverse_links: dict[tuple[int, int], list[tuple[int, int]]] = {}
    connected: set[tuple[int, int]] = set()
    frontier: list[tuple[int, int]] = []

    for (x, y), build_dir in friendly_conveyor_dirs.items():
        pos_tuple = (x, y)
        if Position(x, y).distance_squared(bot.core_pos) <= 2:
            connected.add(pos_tuple)
            frontier.append(pos_tuple)

        if build_dir is None:
            continue

        next_pos = Position(x, y).add(build_dir)
        next_tuple = (next_pos.x, next_pos.y)
        reverse_links.setdefault(next_tuple, []).append(pos_tuple)

    while frontier:
        current = frontier.pop()
        for prev in reverse_links.get(current, ()):
            if prev in connected:
                continue
            connected.add(prev)
            frontier.append(prev)

    bot.connected_friendly_conveyors = connected
