from cambc import Controller, EntityType, Position, Environment
import marker
import logger


def init(self):
    self.core_pos = None
    self.marker_state = marker.MarkerState()
    self.logger = None


def _move_towards(self, ct: Controller, target_pos: Position):
    towards_target = ct.get_position().direction_to(target_pos)
    towards_target_pos = ct.get_position().add(towards_target)
    ct.draw_indicator_dot(towards_target_pos, 0, 255, 0)
    if ct.can_move(towards_target):
        ct.move(towards_target)
    elif ct.can_build_road(towards_target_pos):
        ct.build_road(towards_target_pos)


def _move_away_from_core(self, ct: Controller):
    away_from_core = ct.get_position().direction_to(self.core_pos).opposite()
    away_from_core_pos = ct.get_position().add(away_from_core)
    _move_towards(self, ct, away_from_core_pos)


def scan_around(self, ct: Controller):
    for pos in ct.get_nearby_tiles():
        if (
            ct.get_tile_env(pos) == Environment.ORE_AXIONITE
            or ct.get_tile_env(pos) == Environment.ORE_TITANIUM
        ):
            self.marker_state.ore_locations.add(pos)

    for pos in list(self.marker_state.ore_locations):
        id = ct.get_tile_building_id(pos)
        if (
            id is not None
            and ct.get_entity_type(id) == EntityType.HARVESTER
            and ct.get_team(id) == ct.get_team()
        ):
            self.marker_state.ore_locations.remove(pos)


def run(self, ct: Controller):
    if self.logger is None:
        self.logger = logger.Logger(ct)

    if self.core_pos is None:
        self.core_pos = ct.get_position(
            list(
                filter(
                    lambda id: ct.get_entity_type(id) == EntityType.CORE,
                    ct.get_nearby_entities(),
                )
            )[0]
        )

    self.marker_state.scan_markers(ct)
    scan_around(self, ct)

    self.logger.log("ore locations: {}".format(self.marker_state.ore_locations))

    for pos in self.marker_state.ore_locations:
        if ct.can_build_harvester(pos):
            self.logger.log("building harvester {}".format(pos))
            ct.build_harvester(pos)
            return

    if len(self.marker_state.ore_locations):
        self.logger.log(
            "moving towards ore at {}".format(list(self.marker_state.ore_locations)[0])
        )
        _move_towards(self, ct, list(self.marker_state.ore_locations)[0])
        return

    # move away from the core
    _move_away_from_core(self, ct)
