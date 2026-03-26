from cambc import Controller, Direction, EntityType, Position, Environment
import marker
import logger


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


# non-centre directions in enum order (assumed circular ordering)
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINAL_DIRECTIONS = [
    d
    for d in DIRECTIONS
    if abs(Position(0, 0).add(d).x) + abs(Position(0, 0).add(d).y) == 1
]
MODE_FINDING_ORE = "finding_ore"
MODE_TILING_BACK = "tiling_back"


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
    state = self.bugnav_state

    current_pos = ct.get_position()
    direct_dir = current_pos.direction_to(target_pos)
    direct_pos = current_pos.add(direct_dir)

    # If direct tile can be improved, prioritize road construction.
    if ct.can_build_road(direct_pos):
        ct.build_road(direct_pos)

    # If direct path is clear, take it and exit wall-follow mode.
    if ct.can_move(direct_dir):
        ct.move(direct_dir)
        state["bugging"] = False
        self.bugnav_state = state
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
        if ct.can_build_road(next_pos):
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


def _best_cardinal_dir_towards(from_pos: Position, target_pos: Position):
    best_dir = None
    best_dist = None
    for direction in CARDINAL_DIRECTIONS:
        next_pos = from_pos.add(direction)
        dist = _manhattan(next_pos, target_pos)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_dir = direction
    return best_dir


def _move_cardinal_towards(self, ct: Controller, target_pos: Position):
    return _move_cardinal_towards_excluding(self, ct, target_pos, set())


def _move_cardinal_towards_excluding(
    self, ct: Controller, target_pos: Position, blocked_positions: set[Position]
):
    current_pos = ct.get_position()
    ranked_dirs = sorted(
        CARDINAL_DIRECTIONS,
        key=lambda d: _manhattan(current_pos.add(d), target_pos),
    )

    for direction in ranked_dirs:
        next_pos = current_pos.add(direction)
        if next_pos in blocked_positions:
            continue
        if ct.can_build_road(next_pos):
            ct.build_road(next_pos)
        if ct.can_move(direction):
            ct.move(direction)
            return True

    return False


def _is_between(v: int, a: int, b: int) -> bool:
    return min(a, b) <= v <= max(a, b)


def _is_on_manhattan_line(pos: Position, harvester: Position, core: Position) -> bool:
    on_h_segment = pos.y == harvester.y and _is_between(pos.x, harvester.x, core.x)
    on_v_segment = pos.x == core.x and _is_between(pos.y, harvester.y, core.y)
    return on_h_segment or on_v_segment


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(v, hi))


def _nearest_manhattan_line_point(
    pos: Position, harvester: Position, core: Position
) -> Position:
    # Canonical L path: horizontal from harvester.x -> core.x at y=harvester.y,
    # then vertical at x=core.x from harvester.y -> core.y.
    h_proj = Position(
        _clamp(pos.x, min(harvester.x, core.x), max(harvester.x, core.x)),
        harvester.y,
    )
    v_proj = Position(
        core.x,
        _clamp(pos.y, min(harvester.y, core.y), max(harvester.y, core.y)),
    )

    if _manhattan(pos, h_proj) <= _manhattan(pos, v_proj):
        best = h_proj
    else:
        best = v_proj

    # Harvester tile is blocked; prefer the next closest reachable point on the line.
    if best == harvester and harvester != core:
        if harvester.x != core.x:
            step = 1 if core.x > harvester.x else -1
            return Position(harvester.x + step, harvester.y)
        if harvester.y != core.y:
            step = 1 if core.y > harvester.y else -1
            return Position(harvester.x, harvester.y + step)

    return best


def _line_dir_towards_core(
    pos: Position, harvester: Position, core: Position
) -> Direction | None:
    # Horizontal leg first.
    if (
        pos.y == harvester.y
        and pos.x != core.x
        and _is_between(pos.x, harvester.x, core.x)
    ):
        step = 1 if core.x > pos.x else -1
        return pos.direction_to(Position(pos.x + step, pos.y))

    # Vertical leg at x=core.x.
    if pos.x == core.x and pos.y != core.y and _is_between(pos.y, harvester.y, core.y):
        step = 1 if core.y > pos.y else -1
        return pos.direction_to(Position(pos.x, pos.y + step))

    return None


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

    for pos in self.marker_state.ore_locations:
        if ct.can_build_harvester(pos):
            self.logger.log("building harvester {}".format(pos))
            ct.build_harvester(pos)
            self.last_harvester_pos = pos
            self.tiled_back_positions = set()
            self.builder_mode = MODE_TILING_BACK
            return

    if self.builder_mode == MODE_TILING_BACK:
        current_pos = ct.get_position()
        if self.last_harvester_pos is not None and current_pos != self.core_pos:
            if not _is_on_manhattan_line(
                current_pos, self.last_harvester_pos, self.core_pos
            ):
                line_target = _nearest_manhattan_line_point(
                    current_pos, self.last_harvester_pos, self.core_pos
                )
                self.logger.log("moving to manhattan line at {}".format(line_target))
                if not _move_cardinal_towards_excluding(
                    self, ct, line_target, {self.last_harvester_pos}
                ):
                    _move_towards(self, ct, line_target)
                return

            towards_core = _line_dir_towards_core(
                current_pos, self.last_harvester_pos, self.core_pos
            )
            if (
                towards_core is not None
                and current_pos not in self.tiled_back_positions
            ):
                if not ct.can_build_conveyor(current_pos, towards_core):
                    next_pos = current_pos.add(towards_core)
                    if ct.can_destroy(next_pos):
                        ct.destroy(next_pos)

                if ct.can_build_conveyor(current_pos, towards_core):
                    self.logger.log(
                        "building cardinal conveyor at {} towards {}".format(
                            current_pos, towards_core
                        )
                    )
                    ct.build_conveyor(current_pos, towards_core)
                self.tiled_back_positions.add(current_pos)
                return

        self.logger.log("tiling back to core at {}".format(self.core_pos))
        if not _move_cardinal_towards(self, ct, self.core_pos):
            _move_towards(self, ct, self.core_pos)
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
