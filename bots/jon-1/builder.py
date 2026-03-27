from cambc import (
    Controller,
    Direction,
    EntityType,
    Position,
    Environment,
    GameConstants,
)
import marker
import logger
import math

MIN_TITANIUM_TO_HUNT_AXIONITE = 600
RANDOM_MOVE_MIN_DISTANCE_SQUARED = 25
NEAREST_UNEXPLORED_CHUNK_CANDIDATES = 8

MAX_VISION_ASSUMPTION = math.sqrt(GameConstants.BUILDER_BOT_VISION_RADIUS_SQ) // 3
CHUNK_SIZE = max(1, int(MAX_VISION_ASSUMPTION))

# non-centre directions in enum order (assumed circular ordering)
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINAL_DIRECTIONS = [
    d
    for d in DIRECTIONS
    if abs(Position(0, 0).add(d).x) + abs(Position(0, 0).add(d).y) == 1
]
MODE_FINDING_ORE = "finding_ore"
MODE_EXPLORING = "exploring"
MODE_TILING_BACK = "tiling_back"


def init(self):
    self.core_pos = None
    self.marker_state = marker.MarkerState()

    self.logger = None
    self.bot_locations = set()
    self.bugnav_state = {
        "bugging": False,
        "side": 1,
        "start_dist": float("inf"),
    }
    self.builder_mode = MODE_FINDING_ORE
    self.last_harvester_pos = None
    self.tiled_back_positions = set()
    self.pending_build = None

    self.known_friendly_conveyors = set()
    self.nearest_conveyor_pos = None
    self.nearest_conveyor_dist_manhatten = float("inf")
    self.return_target_pos = None
    self.return_target_dist_manhatten = float("inf")
    self.return_target_kind = "core"
    self.explored_tiles = set()
    self.all_map_chunks = None
    self.explore_target_chunk = None
    self.explore_target_pos = None


def _rotate_directions(
    base_direction: Direction, side: int, directions: list[Direction] = None
):
    if base_direction not in directions:
        return directions

    n = len(directions)
    base_idx = directions.index(base_direction)
    return [directions[(base_idx + side * step) % n] for step in range(n)]


def _best_dir_towards(
    from_pos: Position, target_pos: Position, directions: list[Direction]
):
    return min(directions, key=lambda d: _manhattan(from_pos.add(d), target_pos))


def _is_passable(ct: Controller, current_pos: Position, direction: Direction) -> bool:
    target_pos = current_pos.add(direction)
    return ct.can_move(direction) or ct.can_build_road(target_pos)


def _get_sweep_dirs(
    heading: Direction, side: int, valid_directions: list[Direction]
) -> list[Direction]:
    """
    Builds a sweep of directions hugging the wall.
    side: 1 for right-hand wall, -1 for left-hand wall.
    """
    # 1. Start by turning 135 degrees (3 steps of 45 deg) towards the wall
    curr = heading
    for _ in range(3):
        curr = curr.rotate_right() if side == 1 else curr.rotate_left()

    # 2. Sweep away from the wall, checking 7 directions (omits directly backwards)
    sweep = []
    for _ in range(7):
        if curr in valid_directions:
            sweep.append(curr)
        # Turn away from the wall for the next check
        curr = curr.rotate_left() if side == 1 else curr.rotate_right()

    return sweep


def _get_bugnav_dir(
    self, ct: Controller, target_pos: Position, directions: list[Direction]
) -> Direction | None:
    state = self.bugnav_state
    current_pos = ct.get_position()

    best_dir = min(
        directions, key=lambda d: current_pos.add(d).distance_squared(target_pos)
    )
    current_dist = current_pos.distance_squared(target_pos)

    # 1. Check if direct path is open AND we made progress
    if _is_passable(ct, current_pos, best_dir) and (
        not state["bugging"] or current_dist < state["start_dist"]
    ):
        return best_dir

    # 2. Evaluate Bugnav paths
    if not state["bugging"]:
        # Predict which way we would turn to avoid the wall
        for step in range(1, 4):
            ccw_dir = best_dir
            for _ in range(step):
                ccw_dir = ccw_dir.rotate_left()
            if ccw_dir in directions and _is_passable(ct, current_pos, ccw_dir):
                return ccw_dir

            cw_dir = best_dir
            for _ in range(step):
                cw_dir = cw_dir.rotate_right()
            if cw_dir in directions and _is_passable(ct, current_pos, cw_dir):
                return cw_dir
        return None
    else:
        # We are bugging, generate the sweep based on current heading
        heading = state.get("heading", best_dir)
        side = state.get("side", 1)

        for direction in _get_sweep_dirs(heading, side, directions):
            if _is_passable(ct, current_pos, direction):
                return direction

    return None


def _try_bugnav_move(
    self, ct: Controller, target_pos: Position, directions: list[Direction]
) -> bool:
    state = self.bugnav_state
    current_pos = ct.get_position()

    best_dir = min(
        directions, key=lambda d: current_pos.add(d).distance_squared(target_pos)
    )
    current_dist = current_pos.distance_squared(target_pos)

    move_dir = None

    if _is_passable(ct, current_pos, best_dir) and (
        not state["bugging"] or current_dist < state["start_dist"]
    ):
        move_dir = best_dir
        state["bugging"] = False
        state["heading"] = move_dir
        state["visited"] = set()  # Clear loop memory
    else:
        if not state["bugging"]:
            state["bugging"] = True
            state["start_dist"] = current_dist
            state["visited"] = {current_pos}

            # Initial avoid: lock in handedness based on first open path
            for step in range(1, 4):
                ccw_dir = best_dir
                for _ in range(step):
                    ccw_dir = ccw_dir.rotate_left()
                if ccw_dir in directions and _is_passable(ct, current_pos, ccw_dir):
                    move_dir = ccw_dir
                    state["side"] = 1  # Wall is on the right
                    break

                cw_dir = best_dir
                for _ in range(step):
                    cw_dir = cw_dir.rotate_right()
                if cw_dir in directions and _is_passable(ct, current_pos, cw_dir):
                    move_dir = cw_dir
                    state["side"] = -1  # Wall is on the left
                    break
        else:
            # Full loop detection safety net
            if current_pos in state.get("visited", set()):
                self.logger.log("Bugnav full loop detected! Target is unreachable.")
                state["bugging"] = False
                self.bugnav_state = state
                return False

            state["visited"].add(current_pos)

            heading = state.get("heading", best_dir)
            side = state.get("side", 1)

            for direction in _get_sweep_dirs(heading, side, directions):
                if _is_passable(ct, current_pos, direction):
                    move_dir = direction
                    break

    if move_dir is None:
        return False

    next_pos = current_pos.add(move_dir)

    # Execution logic
    if self.builder_mode != MODE_TILING_BACK:
        if ct.can_build_road(next_pos):
            ct.build_road(next_pos)
    else:
        if _is_passable(ct, current_pos, move_dir) and not ct.can_move(move_dir):
            return False

    if ct.can_move(move_dir):
        ct.move(move_dir)
        state["heading"] = move_dir
        self.bugnav_state = state
        return True

    return False


def _move_towards(
    self, ct: Controller, target_pos: Position, directions: list[Direction]
):
    if ct.get_position() == target_pos:
        return

    ct.draw_indicator_dot(target_pos, 0, 255, 0)
    _try_bugnav_move(self, ct, target_pos, directions)


def _move_away_from_core(self, ct: Controller):
    current_pos = ct.get_position()
    map_width = ct.get_map_width()
    map_height = ct.get_map_height()
    if self.all_map_chunks is None:
        chunk_cols = (map_width + CHUNK_SIZE - 1) // CHUNK_SIZE
        chunk_rows = (map_height + CHUNK_SIZE - 1) // CHUNK_SIZE
        self.all_map_chunks = [
            (cx, cy) for cx in range(chunk_cols) for cy in range(chunk_rows)
        ]

    def _chunk_center(chunk: tuple[int, int]) -> Position:
        return Position(
            min(map_width - 1, chunk[0] * CHUNK_SIZE + CHUNK_SIZE // 2),
            min(map_height - 1, chunk[1] * CHUNK_SIZE + CHUNK_SIZE // 2),
        )

    current_chunk = (current_pos.x // CHUNK_SIZE, current_pos.y // CHUNK_SIZE)

    # Keep current target until it becomes visible (explored).
    if (
        self.explore_target_chunk is not None
        and self.explore_target_chunk in self.explored_tiles
    ):
        self.explore_target_chunk = None
        self.explore_target_pos = None

    if self.explore_target_chunk is None:
        unexplored_chunks = [
            chunk for chunk in self.all_map_chunks if chunk not in self.explored_tiles
        ]

        if not len(unexplored_chunks):
            return

        core_chunk = (self.core_pos.x // CHUNK_SIZE, self.core_pos.y // CHUNK_SIZE)
        unexplored_chunks.sort(
            key=lambda c: (
                abs(c[0] - current_chunk[0]) + abs(c[1] - current_chunk[1]),
                abs(c[0] - core_chunk[0]) + abs(c[1] - core_chunk[1]),
                c[1],
                c[0],
            )
        )
        nearest_chunks = unexplored_chunks[
            : min(NEAREST_UNEXPLORED_CHUNK_CANDIDATES, len(unexplored_chunks))
        ]
        self.explore_target_chunk = nearest_chunks[0]
        self.explore_target_pos = _chunk_center(self.explore_target_chunk)

    if self.explore_target_pos is None and self.explore_target_chunk is not None:
        self.explore_target_pos = _chunk_center(self.explore_target_chunk)

    if self.explore_target_pos is not None:
        _move_towards(self, ct, self.explore_target_pos, DIRECTIONS)
        self.logger.log("exploring towards {}".format(self.explore_target_pos))


def _manhattan(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def _closest_point_on_core_grid(target_pos: Position, from_pos: Position) -> Position:
    return Position(
        max(target_pos.x - 1, min(from_pos.x, target_pos.x + 1)),
        max(target_pos.y - 1, min(from_pos.y, target_pos.y + 1)),
    )


def _closest_cardinal_point_on_core_grid(
    target_pos: Position, from_pos: Position
) -> Position:
    closest_point = _closest_point_on_core_grid(target_pos, from_pos)
    if closest_point.direction_to(target_pos) not in CARDINAL_DIRECTIONS:
        return Position(closest_point.x, target_pos.y)
    return closest_point


def _update_return_target_while_tiling(self, current_pos: Position):
    core_target = _closest_point_on_core_grid(self.core_pos, current_pos)
    best_target = core_target
    best_dist = _manhattan(current_pos, core_target)
    best_kind = "core"

    conveyor_candidates = [
        c
        for c in self.known_friendly_conveyors
        if c != current_pos and c not in self.tiled_back_positions
    ]
    if len(conveyor_candidates):
        nearest_c = min(
            conveyor_candidates,
            key=lambda c_pos: _manhattan(current_pos, c_pos),
        )
        nearest_c_dist = _manhattan(current_pos, nearest_c)
        if nearest_c_dist < best_dist:
            best_target = nearest_c
            best_dist = nearest_c_dist
            best_kind = "conveyor"

    self.return_target_pos = best_target
    self.return_target_dist_manhatten = best_dist
    self.return_target_kind = best_kind
    self.nearest_conveyor_pos = best_target if best_kind == "conveyor" else None
    self.nearest_conveyor_dist_manhatten = (
        best_dist if best_kind == "conveyor" else float("inf")
    )


def scan_around(self, ct: Controller):
    current_pos = ct.get_position()
    self.explored_tiles.add((current_pos.x // CHUNK_SIZE, current_pos.y // CHUNK_SIZE))
    for pos in ct.get_nearby_tiles():
        self.explored_tiles.add((pos.x // CHUNK_SIZE, pos.y // CHUNK_SIZE))
        if ct.get_tile_env(pos) == Environment.ORE_TITANIUM:
            self.marker_state.titanium_locations.add(pos)
        elif ct.get_tile_env(pos) == Environment.ORE_AXIONITE:
            self.marker_state.axionite_locations.add(pos)

    self.bot_locations = set()
    nearby_friendly_conveyors = set()
    for id in ct.get_nearby_entities():
        if (
            ct.get_entity_type(id) == EntityType.BUILDER_BOT
            and ct.get_team(id) == ct.get_team()
        ):
            self.bot_locations.add(ct.get_position(id))
        elif (
            ct.get_entity_type(id)
            == EntityType.HARVESTER
            # and ct.get_team(id) == ct.get_team()
        ):
            self.marker_state.titanium_locations.discard(ct.get_position(id))
            self.marker_state.axionite_locations.discard(ct.get_position(id))
        elif (
            ct.get_entity_type(id) == EntityType.CONVEYOR
            and ct.get_team(id) == ct.get_team()
        ):
            nearby_friendly_conveyors.add(ct.get_position(id))

    self.known_friendly_conveyors.update(nearby_friendly_conveyors)

    for id in ct.get_nearby_buildings():
        if ct.get_team(id) == ct.get_team():
            p = ct.get_position(id)
            self.explored_tiles.add((p.x // CHUNK_SIZE, p.y // CHUNK_SIZE))

    # let another bot go if there's already a bot closer to the ore
    for pos in list(self.marker_state.titanium_locations) + list(
        self.marker_state.axionite_locations
    ):
        d = ct.get_position().distance_squared(pos)
        if any(d > bot_pos.distance_squared(pos) for bot_pos in self.bot_locations):
            self.marker_state.titanium_locations.discard(pos)
            self.marker_state.axionite_locations.discard(pos)


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

    self.logger.log(
        "ore locations: {}".format(
            list(self.marker_state.titanium_locations)
            + list(self.marker_state.axionite_locations)
        )
    )
    self.logger.log("mode: {}".format(self.builder_mode))

    # Stop exploring immediately once ore is discovered.
    if self.builder_mode == MODE_EXPLORING and len(
        self.marker_state.titanium_locations
    ):
        self.builder_mode = MODE_FINDING_ORE
        self.explore_target_chunk = None
        self.explore_target_pos = None

    if self.builder_mode == MODE_TILING_BACK:
        current_pos = ct.get_position()

        # Re-evaluate nearest return candidate as we move and discover more conveyors.
        _update_return_target_while_tiling(self, current_pos)

        target_pos = (
            self.return_target_pos
            if self.return_target_pos is not None
            else self.core_pos
        )
        target_kind = self.return_target_kind

        if target_kind == "core":
            target_pos = _closest_point_on_core_grid(self.core_pos, current_pos)

        if (
            target_kind == "core"
            and current_pos.distance_squared(target_pos) == 0
            and not self.pending_build
        ):
            self.builder_mode = MODE_FINDING_ORE
            return

        self.logger.log(
            "state: pending build {}, return target {}, return target kind {}".format(
                self.pending_build,
                self.return_target_pos,
                self.return_target_kind,
            )
        )

        if (
            target_kind == "conveyor"
            and _manhattan(current_pos, target_pos) == 1
            and not self.pending_build
        ):
            connect_dir = current_pos.direction_to(target_pos)
            connected = False
            if not ct.can_build_conveyor(current_pos, connect_dir):
                # TODO deny destroying more usefull stuff
                if (
                    ct.can_destroy(current_pos)
                    and ct.get_entity_type(ct.get_tile_building_id(current_pos))
                    != EntityType.CONVEYOR
                ):
                    self.logger.log(
                        "destroying {} at {} to build conveyor toward {}".format(
                            ct.get_entity_type(ct.get_tile_building_id(current_pos)),
                            current_pos,
                            connect_dir,
                        )
                    )
                    ct.destroy(current_pos)
            if ct.can_build_conveyor(current_pos, connect_dir):
                self.logger.log(
                    "tiling back, connecting to nearby conveyor at {} from {}".format(
                        target_pos, current_pos
                    )
                )
                ct.build_conveyor(current_pos, connect_dir)
                self.tiled_back_positions.add(current_pos)
                connected = True
            elif (
                ct.get_entity_type(ct.get_tile_building_id(current_pos))
                == EntityType.CONVEYOR
                and ct.get_direction(ct.get_tile_building_id(current_pos))
                == connect_dir
            ):
                connected = True

            if connected:
                self.builder_mode = MODE_FINDING_ORE
                return

        if self.pending_build is not None:
            build_pos, build_dir = self.pending_build
            if ct.can_build_conveyor(build_pos, build_dir):
                self.logger.log(
                    "executing pending build of conveyor at {} toward {}".format(
                        build_pos, build_dir
                    )
                )
                ct.build_conveyor(build_pos, build_dir)
                self.tiled_back_positions.add(build_pos)
                self.pending_build = None
            else:
                self.logger.log(
                    "still can't execute pending build of conveyor at {} toward {}, maybe still blocked?".format(
                        build_pos, build_dir
                    )
                )
            return

        # Move toward core using cardinal-only bugnav.

        # Lay a conveyor at this position pointing in the direction we intend to
        # travel next turn. We peek at the bugnav decision without executing it
        # so that the conveyor direction matches the actual path taken, keeping
        # the chain connected even when detouring around obstacles.

        # TODO, build road behind us instead of conveyor because of conveyor cost scaling factor
        move_dir = _get_bugnav_dir(self, ct, target_pos, CARDINAL_DIRECTIONS)
        if move_dir is not None:
            if not ct.can_build_conveyor(current_pos, move_dir):

                # TODO allow destroying of less useful stuff
                id = ct.get_tile_building_id(current_pos)
                if ct.can_destroy(current_pos):
                    if ct.get_entity_type(id) in [
                        EntityType.MARKER,
                        EntityType.ROAD,
                    ]:
                        self.logger.log(
                            "destroying {} at {} to build conveyor toward {}".format(
                                ct.get_entity_type(id), current_pos, move_dir
                            )
                        )
                        ct.destroy(current_pos)
                    # wrong direction
                    elif (
                        ct.get_entity_type(id) == EntityType.CONVEYOR
                        and ct.get_direction(id) != move_dir
                    ):
                        self.logger.log(
                            "destroying misaligned conveyor at {} to build conveyor toward {}".format(
                                current_pos, move_dir
                            )
                        )
                        ct.destroy(current_pos)

            self.logger.log(
                "tiling back, nearest conveyor distance {}, core distance {}, moving toward {} at {}".format(
                    self.nearest_conveyor_dist_manhatten,
                    _manhattan(current_pos, self.core_pos),
                    target_kind,
                    target_pos,
                )
            )
            can_move = _try_bugnav_move(self, ct, target_pos, CARDINAL_DIRECTIONS)
            if can_move:
                if ct.can_build_conveyor(current_pos, move_dir):
                    self.logger.log(
                        "building conveyor at {} toward {}".format(
                            current_pos, move_dir
                        )
                    )
                    ct.build_conveyor(current_pos, move_dir)
                    self.tiled_back_positions.add(current_pos)
                else:
                    if (
                        ct.get_entity_type(ct.get_tile_building_id(current_pos))
                        != EntityType.CONVEYOR
                        and ct.get_global_resources() < ct.get_conveyor_cost()
                    ):
                        self.logger.log(
                            "can't build conveyor at {} toward {} due to insufficient resources".format(
                                current_pos, move_dir
                            )
                        )
                        self.pending_build = (current_pos, move_dir)
            else:
                # for tiling back, build conveyors if there's space to build
                next_pos = ct.get_position().add(move_dir)

                self.logger.log(
                    "can't move toward {} {} from {}, maybe blocked? trying to build conveyor on {}".format(
                        target_kind,
                        target_pos,
                        current_pos,
                        next_pos,
                    )
                )
                next_pos_best_dir = _best_dir_towards(
                    next_pos, target_pos, CARDINAL_DIRECTIONS
                )
                self.logger.log(
                    "best dir from {} to target is {}, checking if we can build conveyor there? {}".format(
                        next_pos,
                        next_pos_best_dir,
                        ct.can_build_conveyor(next_pos, next_pos_best_dir),
                    )
                )
                if ct.can_build_conveyor(next_pos, next_pos_best_dir):
                    ct.build_conveyor(next_pos, next_pos_best_dir)
                    self.tiled_back_positions.add(next_pos)
            return

    elif self.builder_mode == MODE_FINDING_ORE:
        if len(self.marker_state.titanium_locations):
            can_target_ore = []
            # TODO find axiomite maybe?
            for pos in list(self.marker_state.titanium_locations) + list(
                self.marker_state.axionite_locations
            ):
                closest_pos = _closest_point_on_core_grid(pos, ct.get_position())
                d = ct.get_position().distance_squared(closest_pos)
                if all(
                    d
                    <= bot_pos.distance_squared(
                        _closest_point_on_core_grid(pos, bot_pos)
                    )
                    for bot_pos in self.bot_locations
                ):
                    can_target_ore.append((pos, closest_pos, d))
            can_target_ore.sort(key=lambda x: x[1])

            if len(can_target_ore):
                pos, closest_pos, d = min(can_target_ore, key=lambda x: x[2])

                if (
                    ct.can_build_harvester(pos)
                    and _manhattan(pos, ct.get_position())
                    == 1  # only build on adjacent cardinal
                ):
                    self.logger.log("building harvester {}".format(pos))
                    ct.build_harvester(pos)
                    self.last_harvester_pos = pos
                    self.tiled_back_positions = set()
                    self.nearest_conveyor_pos = None
                    self.nearest_conveyor_dist_manhatten = float("inf")
                    self.return_target_pos = _closest_point_on_core_grid(
                        self.core_pos, ct.get_position()
                    )
                    self.return_target_dist_manhatten = _manhattan(
                        ct.get_position(), self.return_target_pos
                    )
                    self.return_target_kind = "core"
                    self.bugnav_state = {"bugging": False, "side": 1}
                    self.builder_mode = MODE_TILING_BACK
                    self.explore_target_chunk = None
                    self.explore_target_pos = None

                    # find suitable target conveyor to connect to after mining the ore

                    visible_candidates = [c for c in self.known_friendly_conveyors]
                    best_target = _closest_point_on_core_grid(self.core_pos, pos)
                    best_dist = _manhattan(pos, best_target)
                    best_kind = "core"

                    if visible_candidates:
                        nearest_c = min(
                            visible_candidates, key=lambda c_pos: _manhattan(pos, c_pos)
                        )
                        nearest_c_dist = _manhattan(pos, nearest_c)
                        if nearest_c_dist < best_dist:
                            best_target = nearest_c
                            best_dist = nearest_c_dist
                            best_kind = "conveyor"

                    self.return_target_pos = best_target
                    self.return_target_dist_manhatten = best_dist
                    self.return_target_kind = best_kind
                    return

                if (
                    ct.get_global_resources()[0] < ct.get_harvester_cost()[0]
                    or ct.get_global_resources()[0] < ct.get_conveyor_cost()[0]
                ):
                    self.logger.log(
                        "don't explore when resources are low: {}".format(
                            ct.get_global_resources()[0]
                        )
                    )
                    return

                if _manhattan(ct.get_position(), pos) <= 1:
                    self.logger.log(
                        "standing on ore at {}, trying to build harvester, {}/{}".format(
                            pos, ct.get_global_resources(), ct.get_harvester_cost()
                        )
                    )
                    return

                self.logger.log("moving towards ore at {}".format(pos))
                _move_towards(self, ct, pos, DIRECTIONS)
                return

        # Nothing actionable: switch into deterministic explore mode.
        self.builder_mode = MODE_EXPLORING
        _move_away_from_core(self, ct)
    elif self.builder_mode == MODE_EXPLORING:
        _move_away_from_core(self, ct)
    else:
        self.logger.print("unknown mode: {}".format(self.builder_mode))
