from cambc import Controller, Direction, EntityType, Position, Environment
import marker
import logger


# non-centre directions in enum order (assumed circular ordering)
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINAL_DIRECTIONS = [
    d
    for d in DIRECTIONS
    if abs(Position(0, 0).add(d).x) + abs(Position(0, 0).add(d).y) == 1
]
MODE_FINDING_ORE = "finding_ore"
MODE_TILING_BACK = "tiling_back"


def init(self):
    self.core_pos = None
    self.marker_state = marker.MarkerState()
    self.logger = None
    self.bot_locations = set()
    self.bugnav_state = {
        "bugging": False,
        "side": 1,
    }
    self.builder_mode = MODE_FINDING_ORE
    self.last_harvester_pos = None
    self.tiled_back_positions = set()
    self.harvester_linked = False


def _rotate_directions(base_direction: Direction, side: int, directions: list = None):
    if directions is None:
        directions = DIRECTIONS
    if base_direction not in directions:
        return directions

    n = len(directions)
    base_idx = directions.index(base_direction)
    return [directions[(base_idx + side * step) % n] for step in range(n)]


def _best_dir_towards(
    from_pos: Position, target_pos: Position, directions: list = None
):
    if directions is None:
        directions = DIRECTIONS
    return min(directions, key=lambda d: _manhattan(from_pos.add(d), target_pos))


def _get_bugnav_dir(
    self, ct: Controller, target_pos: Position, directions: list = None
) -> Direction | None:
    """Return the direction bugnav would move without executing it."""
    if directions is None:
        directions = DIRECTIONS
    state = self.bugnav_state
    current_pos = ct.get_position()
    best_dir = _best_dir_towards(current_pos, target_pos, directions)

    if ct.can_move(best_dir):
        return best_dir

    if state["bugging"]:
        side = state["side"]
    else:
        cw_open = sum(
            1 for d in _rotate_directions(best_dir, 1, directions)[1:] if ct.can_move(d)
        )
        ccw_open = sum(
            1
            for d in _rotate_directions(best_dir, -1, directions)[1:]
            if ct.can_move(d)
        )
        side = 1 if cw_open >= ccw_open else -1

    for direction in _rotate_directions(best_dir, side, directions):
        if ct.can_move(direction):
            return direction

    return None


def _try_bugnav_move(
    self, ct: Controller, target_pos: Position, directions: list = None
) -> bool:
    if directions is None:
        directions = DIRECTIONS
    state = self.bugnav_state
    current_pos = ct.get_position()
    best_dir = _best_dir_towards(current_pos, target_pos, directions)

    # Opportunistically build roads only when navigating freely (not tiling back).
    if directions is DIRECTIONS:
        direct_pos = current_pos.add(best_dir)
        if ct.can_build_road(direct_pos):
            ct.build_road(direct_pos)

    if ct.can_move(best_dir):
        ct.move(best_dir)
        state["bugging"] = False
        self.bugnav_state = state
        return True

    if not state["bugging"]:
        cw_open = sum(
            1 for d in _rotate_directions(best_dir, 1, directions)[1:] if ct.can_move(d)
        )
        ccw_open = sum(
            1
            for d in _rotate_directions(best_dir, -1, directions)[1:]
            if ct.can_move(d)
        )
        state["side"] = 1 if cw_open >= ccw_open else -1
        state["bugging"] = True

    for direction in _rotate_directions(best_dir, state["side"], directions):
        next_pos = current_pos.add(direction)
        if directions is DIRECTIONS and ct.can_build_road(next_pos):
            ct.build_road(next_pos)
        if ct.can_move(direction):
            ct.move(direction)
            self.bugnav_state = state
            return True

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


def _manhattan(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


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
            self.marker_state.ore_locations.discard(ct.get_position(id))


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
    self.logger.log("mode: {}".format(self.builder_mode))

    if self.builder_mode == MODE_TILING_BACK:
        current_pos = ct.get_position()

        if current_pos == self.core_pos:
            self.builder_mode = MODE_FINDING_ORE
            return

        # First turn after building: bridge the gap from the harvester to the bot.
        if not self.harvester_linked:
            # Figure out which way the conveyor should point to reach the bot
            dir_to_bot = self.last_harvester_pos.direction_to(current_pos)

            # Target the empty tile directly adjacent to the harvester
            first_belt_pos = self.last_harvester_pos.add(dir_to_bot)

            # If the bot is already standing on that exact tile, normal tiling handles it.
            # Otherwise, build a conveyor there to bridge the gap.
            if first_belt_pos != current_pos and ct.can_build_conveyor(
                first_belt_pos, dir_to_bot
            ):
                self.logger.log(
                    "linking harvester output at {} toward {}".format(
                        first_belt_pos, current_pos
                    )
                )
                ct.build_conveyor(first_belt_pos, dir_to_bot)

            self.harvester_linked = True
            return

        # Move toward core using cardinal-only bugnav.

        # Lay a conveyor at this position pointing in the direction we intend to
        # travel next turn. We peek at the bugnav decision without executing it
        # so that the conveyor direction matches the actual path taken, keeping
        # the chain connected even when detouring around obstacles.
        if current_pos not in self.tiled_back_positions:
            move_dir = _get_bugnav_dir(self, ct, self.core_pos, CARDINAL_DIRECTIONS)
            if move_dir is not None:
                if not ct.can_build_conveyor(current_pos, move_dir):
                    if ct.can_destroy(current_pos):
                        ct.destroy(current_pos)

                self.logger.log(
                    "tiling back, moving toward core at {}".format(self.core_pos)
                )
                _try_bugnav_move(self, ct, self.core_pos, CARDINAL_DIRECTIONS)
                if ct.can_build_conveyor(current_pos, move_dir):
                    self.logger.log(
                        "building conveyor at {} toward {}".format(
                            current_pos, move_dir
                        )
                    )
                    ct.build_conveyor(current_pos, move_dir)
            self.tiled_back_positions.add(current_pos)
            return

    elif self.builder_mode == MODE_FINDING_ORE:
        for pos in list(self.marker_state.ore_locations):
            if ct.can_build_harvester(pos):
                self.logger.log("building harvester {}".format(pos))
                ct.build_harvester(pos)
                self.last_harvester_pos = pos
                self.harvester_linked = pos.distance_squared(ct.get_position()) == 1
                self.tiled_back_positions = set()
                self.bugnav_state = {"bugging": False, "side": 1}
                self.builder_mode = MODE_TILING_BACK
                return

        if len(self.marker_state.ore_locations):
            can_target_ore = []
            for pos in list(self.marker_state.ore_locations):
                # let another bot go if there's already a bot closer to the ore
                d = ct.get_position().distance_squared(pos)
                if all(
                    d <= bot_pos.distance_squared(pos) for bot_pos in self.bot_locations
                ):
                    can_target_ore.append((pos, d))

            can_target_ore.sort(key=lambda x: x[1])
            if len(can_target_ore):
                pos, d = min(can_target_ore, key=lambda x: x[1])
                self.logger.log("moving towards ore at {}".format(pos))
                _move_towards(self, ct, pos)
                return

        # move away from the core
        _move_away_from_core(self, ct)
    else:
        self.logger.print("unknown mode: {}".format(self.builder_mode))
