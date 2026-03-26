from cambc import Controller, Direction, EntityType, Position, Environment
import marker
import logger


def init(self):
    self.core_pos = None
    self.marker_state = marker.MarkerState()
    self.logger = None
    self.bot_locations = set()
    self.bugnav_state = {}


# non-centre directions in enum order (assumed circular ordering)
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]


def _get_self_id(self, ct: Controller):
    my_pos = ct.get_position()
    for id in ct.get_nearby_entities():
        if (
            ct.get_entity_type(id) == EntityType.BUILDER_BOT
            and ct.get_team(id) == ct.get_team()
            and ct.get_position(id) == my_pos
        ):
            return id
    return None


def _rotate_directions(base_direction: Direction, side: int):
    if base_direction not in DIRECTIONS:
        return DIRECTIONS

    n = len(DIRECTIONS)
    base_idx = DIRECTIONS.index(base_direction)
    rotated = []
    for step in range(n):
        idx = (base_idx + (side * step)) % n
        rotated.append(DIRECTIONS[idx])
    return rotated


def _try_bugnav_move(self, ct: Controller, target_pos: Position):
    my_id = _get_self_id(self, ct)
    if my_id is None:
        return False

    state = self.bugnav_state.get(
        my_id,
        {
            "bugging": False,
            "side": 1,
        },
    )

    current_pos = ct.get_position()
    direct_dir = current_pos.direction_to(target_pos)
    direct_pos = current_pos.add(direct_dir)

    # If direct path is clear, take it and exit wall-follow mode.
    if ct.can_move(direct_dir):
        ct.move(direct_dir)
        state["bugging"] = False
        self.bugnav_state[my_id] = state
        return True

    # If direct tile can be improved, prioritize road construction.
    if ct.can_build_road(direct_pos):
        ct.build_road(direct_pos)
        self.bugnav_state[my_id] = state
        return True

    # Enter bug mode and pick a side if not already following a wall.
    if not state["bugging"]:
        cw_dirs = _rotate_directions(direct_dir, 1)
        ccw_dirs = _rotate_directions(direct_dir, -1)

        cw_open = 0
        ccw_open = 0
        for i in range(1, min(4, len(DIRECTIONS))):
            if ct.can_move(cw_dirs[i]):
                cw_open += 1
            if ct.can_move(ccw_dirs[i]):
                ccw_open += 1

        state["side"] = 1 if cw_open >= ccw_open else -1
        state["bugging"] = True

    # Follow wall by rotating around blocked direct heading.
    for direction in _rotate_directions(direct_dir, state["side"]):
        next_pos = current_pos.add(direction)
        if ct.can_move(direction):
            ct.move(direction)
            self.bugnav_state[my_id] = state
            return True
        if ct.can_build_road(next_pos):
            ct.build_road(next_pos)
            self.bugnav_state[my_id] = state
            return True

    self.bugnav_state[my_id] = state
    return False


def _move_towards(self, ct: Controller, target_pos: Position):
    if ct.get_position() == target_pos:
        return

    ct.draw_indicator_dot(target_pos, 0, 255, 0)
    _try_bugnav_move(self, ct, target_pos)


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

    self.bot_locations = set()
    for id in ct.get_nearby_entities():
        if (
            ct.get_entity_type(id) == EntityType.BUILDER_BOT
            and ct.get_team(id) == ct.get_team()
        ):
            self.bot_locations.add(ct.get_position(id))
        elif (
            ct.get_entity_type(id) == EntityType.HARVESTER
            and ct.get_team(id) == ct.get_team()
        ):
            self.marker_state.ore_locations.remove(ct.get_position(id))


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
        for pos in list(self.marker_state.ore_locations):
            # let another bot go if there's already a bot closer to the ore
            if all(
                ct.get_position().distance_squared(pos) <= bot_pos.distance_squared(pos)
                for bot_pos in self.bot_locations
            ):
                self.logger.log("moving towards ore at {}".format(pos))
                _move_towards(self, ct, pos)
                return

    # move away from the core
    _move_away_from_core(self, ct)
