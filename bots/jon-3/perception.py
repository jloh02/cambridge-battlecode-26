from cambc import Controller, EntityType, Environment, GameConstants, Position
import math

MAX_VISION_ASSUMPTION = math.sqrt(GameConstants.BUILDER_BOT_VISION_RADIUS_SQ) - 1
CHUNK_SIZE = max(1, int(MAX_VISION_ASSUMPTION))

# Entities that do not block movement
PASSABLE_ENTITIES = {
    EntityType.ROAD,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.CORE,
    EntityType.BUILDER_BOT,
}


def scan_around(bot, ct: Controller):
    """Main perception entry point."""
    _update_exploration_chunks(bot, ct)
    _update_master_grid(bot, ct)
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

    # 2. Map Dynamic Entities
    for id in ct.get_nearby_entities():
        pos = ct.get_position(id)
        pos_tuple = (pos.x, pos.y)

        if pos_tuple not in bot.grid:
            bot.grid[pos_tuple] = {}

        bot.grid[pos_tuple]["entity"] = ct.get_entity_type(id)
        bot.grid[pos_tuple]["entity_team"] = ct.get_team(id)
        bot.grid[pos_tuple]["last_seen"] = current_round

    # 3. Map Buildings
    for id in ct.get_nearby_buildings():
        pos = ct.get_position(id)
        pos_tuple = (pos.x, pos.y)

        if pos_tuple not in bot.grid:
            bot.grid[pos_tuple] = {}

        bot.grid[pos_tuple]["building"] = ct.get_entity_type(id)
        bot.grid[pos_tuple]["building_team"] = ct.get_team(id)
        bot.grid[pos_tuple]["last_seen"] = current_round


def _infer_state_from_grid(bot, ct: Controller):
    """Parses the grid to generate lists needed for decision making and A*."""
    # Reset states for the current tick
    bot.titanium_locations.clear()
    bot.axionite_locations.clear()
    bot.pathfinding_state["known_obstacles"].clear()
    bot.bot_locations.clear()

    my_team = ct.get_team()

    for (x, y), data in bot.grid.items():
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

        # --- 2. Obstacles ---
        is_obstacle = False

        if env == Environment.WALL:
            is_obstacle = True

        if entity == EntityType.HARVESTER:
            is_obstacle = True
        elif entity is not None and entity not in PASSABLE_ENTITIES:
            is_obstacle = True

        if building is not None and building not in PASSABLE_ENTITIES:
            is_obstacle = True

        if is_obstacle:
            bot.pathfinding_state["known_obstacles"].add((x, y))

        # --- 3. Allies ---
        if entity == EntityType.BUILDER_BOT and data.get("entity_team") == my_team:
            bot.bot_locations.add(pos)

        if building == EntityType.CONVEYOR and data.get("building_team") == my_team:
            bot.known_friendly_conveyors.add(pos)
