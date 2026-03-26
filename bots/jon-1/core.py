from cambc import (
    Controller,
    Direction,
    EntityType,
    Environment,
    Position,
)
import random
import marker
import logger

MIN_UNIT_COUNT = 6  # 8 builders in all direction + core
SPAWN_BUILDER_INTERVAL_IN_TURNS = 10
RESOURCE_MIN_SPAWN_BUILDER = 500
RESOURCE_MAX_SPAWN_BUILDER = 2000

SPAWN_DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]


def init(self):
    random.shuffle(SPAWN_DIRECTIONS)

    self.next_spawn_idx = 0

    self.last_spawn_turn = -SPAWN_BUILDER_INTERVAL_IN_TURNS
    self.marker_state = marker.MarkerState()
    self.logger = None


def _spawn_random_around(self, ct: Controller):
    direction = SPAWN_DIRECTIONS[self.next_spawn_idx]

    if self.next_spawn_idx == len(SPAWN_DIRECTIONS) - 1:
        self.next_spawn_idx = 0
        random.shuffle(SPAWN_DIRECTIONS)
    else:
        self.next_spawn_idx += 1
    spawn_pos = ct.get_position().add(direction)

    # loop surrounding entities to find target spawn and if we can destroy marker
    # Update: don't need this, just replace friendly is allowed
    # for id in ct.get_nearby_entities():
    #     if (
    #         ct.get_entity_type(id) == EntityType.MARKER
    #         and ct.get_team(id) == ct.get_team()
    #     ):
    #         marker_pos = ct.get_position(id)
    #         if marker_pos == spawn_pos and ct.can_destroy(id):
    #             ct.destroy(id)

    if ct.can_spawn(spawn_pos):
        # just don't spawn markers first, it clogs space and there's no much yield
        # builders can see almost as far as the core

        # _place_marker_direction_around(self, ct, spawn_pos)
        ct.spawn_builder(spawn_pos)
        self.last_spawn_turn = ct.get_current_round()


def run(self, ct: Controller):
    if self.logger is None:
        self.logger = logger.Logger(ct)

    # scan phase
    self.marker_state.scan_markers(ct)
    # _get_titanium_locations_in_priority_order(self, ct)

    self.logger.log("ore locations: {}".format(self.marker_state.titanium_locations))

    if (
        # early game, spawn builder bots
        # spawn builder bots until we have a certain number of units
        ct.get_unit_count()
        < MIN_UNIT_COUNT
    ):
        _spawn_random_around(self, ct)
    elif (
        ct.get_current_round() - self.last_spawn_turn >= SPAWN_BUILDER_INTERVAL_IN_TURNS
    ):
        if (
            RESOURCE_MIN_SPAWN_BUILDER
            <= ct.get_global_resources()[0]
            <= RESOURCE_MAX_SPAWN_BUILDER
        ):
            _spawn_random_around(self, ct)
            self.last_spawn_turn = ct.get_current_round()


def _get_titanium_locations_in_priority_order(self, ct: Controller):
    titanium_locations_tmp = []
    for pos in ct.get_nearby_tiles():
        if (
            ct.get_tile_env(pos) == Environment.ORE_AXIONITE
            or ct.get_tile_env(pos) == Environment.ORE_TITANIUM
        ):
            titanium_locations_tmp.append(
                (
                    ct.get_position().distance_squared(pos),
                    pos,
                )
            )
    self.marker_state.update_titanium_locations(
        list(map(lambda x: x[1], sorted(titanium_locations_tmp, key=lambda x: x[0])))
    )


def _place_marker_direction_around(self, ct: Controller, spawn_pos: Position):
    for direction in SPAWN_DIRECTIONS:
        marker_pos = spawn_pos.add(direction)

        # destroy marker if we had one there
        for id in ct.get_nearby_entities():
            if (
                ct.get_entity_type(id) == EntityType.MARKER
                and ct.get_team(id) == ct.get_team()
            ):

                if ct.get_position(id) == marker_pos and ct.can_destroy(
                    ct.get_position(id)
                ):
                    ct.destroy(id)

        if ct.can_place_marker(marker_pos):
            ct.place_marker(
                marker_pos,
                marker._create_ore_marker(
                    self.marker_state.titanium_locations,
                    ct.get_map_width(),
                    ct.get_map_height(),
                ),
            )
            self.logger.print("placed marker at {}".format(marker_pos))
            return
