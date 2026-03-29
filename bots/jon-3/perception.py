from cambc import Controller, EntityType, Environment, GameConstants
import math

MAX_VISION_ASSUMPTION = math.sqrt(GameConstants.BUILDER_BOT_VISION_RADIUS_SQ) // 2
CHUNK_SIZE = max(1, int(MAX_VISION_ASSUMPTION))


def scan_around(bot, ct: Controller):
    current_pos = ct.get_position()
    bot.explored_tiles.add((current_pos.x // CHUNK_SIZE, current_pos.y // CHUNK_SIZE))

    for pos in ct.get_nearby_tiles():
        bot.explored_tiles.add((pos.x // CHUNK_SIZE, pos.y // CHUNK_SIZE))
        if ct.get_tile_env(pos) == Environment.ORE_TITANIUM:
            bot.titanium_locations.add(pos)
        elif ct.get_tile_env(pos) == Environment.ORE_AXIONITE:
            bot.axionite_locations.add(pos)

    bot.bot_locations = set()
    nearby_friendly_conveyors = set()

    for id in ct.get_nearby_entities():
        if (
            ct.get_entity_type(id) == EntityType.BUILDER_BOT
            and ct.get_team(id) == ct.get_team()
        ):
            bot.bot_locations.add(ct.get_position(id))
        elif ct.get_entity_type(id) == EntityType.HARVESTER:
            bot.titanium_locations.discard(ct.get_position(id))
            bot.axionite_locations.discard(ct.get_position(id))
        elif (
            ct.get_entity_type(id) == EntityType.CONVEYOR
            and ct.get_team(id) == ct.get_team()
        ):
            nearby_friendly_conveyors.add(ct.get_position(id))

    bot.known_friendly_conveyors.update(nearby_friendly_conveyors)

    for id in ct.get_nearby_buildings():
        if ct.get_team(id) == ct.get_team():
            p = ct.get_position(id)
            bot.explored_tiles.add((p.x // CHUNK_SIZE, p.y // CHUNK_SIZE))

    # ? Update on 28/03: Just race for it since we don't know which bots are in which state
    # Let another bot go if there's already a bot closer to the ore
    # for pos in list(bot.titanium_locations) + list(bot.axionite_locations):
    #     d = ct.get_position().distance_squared(pos)
    #     if any(d > bot_pos.distance_squared(pos) for bot_pos in bot.bot_locations):
    #         bot.titanium_locations.discard(pos)
    #         bot.axionite_locations.discard(pos)
