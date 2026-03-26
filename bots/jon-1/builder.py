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
import random
import math

MIN_TITANIUM_TO_HUNT_AXIONITE = 2000
RANDOM_MOVE_MIN_DISTANCE_SQUARED = 25
EXPANDING_SEARCH_RADIUS_CELL_PER_ROUND = 0.25
EXPANDING_SEARCH_RADIUS_CELL_PER_UNIT = 0.35
BASE_SEARCH_RADIUS_CELLS = 3

MAX_VISION_ASSUMPTION = math.sqrt(GameConstants.BUILDER_BOT_VISION_RADIUS_SQ)
CHUNK_SIZE = max(1, int(MAX_VISION_ASSUMPTION))

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
    self.ore_positions = set()

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
    self.harvester_linked = False
    self.pending_build = None

    self.known_friendly_conveyors = set()
    self.nearest_conveyor_pos = None
    self.nearest_conveyor_dist_sq = float("inf")
    self.return_target_pos = None
    self.return_target_dist_sq = float("inf")
    self.return_target_kind = "core"
    self.explored_tiles = set()


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


def _get_bugnav_dir(
    self, ct: Controller, target_pos: Position, directions: list[Direction]
) -> Direction | None:
    state = self.bugnav_state
    current_pos = ct.get_position()
    best_dir = _best_dir_towards(current_pos, target_pos, directions)

    current_dist = current_pos.distance_squared(target_pos)

    if _is_passable(ct, current_pos, best_dir) and (
        not state["bugging"] or current_dist < state["start_dist"]
    ):
        return best_dir

    if state["bugging"]:
        side = state["side"]
    else:
        cw_open = sum(
            1
            for d in _rotate_directions(best_dir, 1, directions)[1:]
            if _is_passable(ct, current_pos, d)
        )
        ccw_open = sum(
            1
            for d in _rotate_directions(best_dir, -1, directions)[1:]
            if _is_passable(ct, current_pos, d)
        )
        side = 1 if cw_open >= ccw_open else -1

    for direction in _rotate_directions(best_dir, side, directions):
        if _is_passable(ct, current_pos, direction):
            return direction

    return None


def _try_bugnav_move(
    self, ct: Controller, target_pos: Position, directions: list[Direction]
) -> bool:
    state = self.bugnav_state
    current_pos = ct.get_position()
    best_dir = _best_dir_towards(current_pos, target_pos, directions)

    move_dir = None

    # 1. Decide where to go using the new passability check
    current_dist = current_pos.distance_squared(target_pos)

    # We only take the direct path if it's passable AND (we aren't bugging OR we made progress)
    if _is_passable(ct, current_pos, best_dir) and (
        not state["bugging"] or current_dist < state["start_dist"]
    ):
        move_dir = best_dir
        state["bugging"] = False
    else:
        if not state["bugging"]:
            # Record the distance when we first hit the wall
            state["start_dist"] = current_dist
            cw_open = sum(
                1
                for d in _rotate_directions(best_dir, 1, directions)[1:]
                if _is_passable(ct, current_pos, d)
            )
            ccw_open = sum(
                1
                for d in _rotate_directions(best_dir, -1, directions)[1:]
                if _is_passable(ct, current_pos, d)
            )
            state["side"] = 1 if cw_open >= ccw_open else -1
            state["bugging"] = True

        for direction in _rotate_directions(best_dir, state["side"], directions):
            if _is_passable(ct, current_pos, direction):
                move_dir = direction
                break

    # If totally blocked, exit
    if move_dir is None:
        return False

    next_pos = current_pos.add(move_dir)

    # 2. Execute the build and move along the chosen direction
    if self.builder_mode != MODE_TILING_BACK:
        if ct.can_build_road(next_pos):
            ct.build_road(next_pos)
    else:
        # early exit so we can fill with conveyor instead of road while tiling
        if _is_passable(ct, current_pos, move_dir) and not ct.can_move(move_dir):
            return False

    if ct.can_move(move_dir):
        ct.move(move_dir)
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

    # Track explored space as coarse chunks for cheaper frontier decisions.
    self.explored_tiles.add((current_pos.x // CHUNK_SIZE, current_pos.y // CHUNK_SIZE))

    # Mark chunks with nearby infrastructure as explored.
    building_types = {
        EntityType.CORE,
        EntityType.ROAD,
        EntityType.MARKER,
        EntityType.HARVESTER,
        EntityType.CONVEYOR,
    }
    for id in ct.get_nearby_entities():
        if ct.get_entity_type(id) in building_types:
            p = ct.get_position(id)
            self.explored_tiles.add((p.x // CHUNK_SIZE, p.y // CHUNK_SIZE))

    # Expanding exploration circle based on game progress and map presence.
    expansion_radius_cells = (
        BASE_SEARCH_RADIUS_CELLS
        + ct.get_current_round() * EXPANDING_SEARCH_RADIUS_CELL_PER_ROUND
        + ct.get_unit_count() * EXPANDING_SEARCH_RADIUS_CELL_PER_UNIT
    )
    expansion_radius_sq = int(expansion_radius_cells * expansion_radius_cells)

    # Gather valid passable directions.
    valid_dirs = []
    for d in DIRECTIONS:
        target_pos = current_pos.add(d)
        if ct.can_move(d) or ct.can_build_road(target_pos):
            valid_dirs.append(d)

    if not valid_dirs:
        return

    # Keep movement mostly inside the current expansion circle.
    in_circle_dirs = [
        d
        for d in valid_dirs
        if current_pos.add(d).distance_squared(self.core_pos) <= expansion_radius_sq
    ]
    candidate_dirs = in_circle_dirs if len(in_circle_dirs) else valid_dirs

    # Prefer directions whose projected chunk is unexplored.
    unexplored_dirs = []
    for d in candidate_dirs:
        step = Position(0, 0).add(d)
        projected = Position(
            int(current_pos.x + step.x * CHUNK_SIZE),
            int(current_pos.y + step.y * CHUNK_SIZE),
        )
        projected_chunk = (projected.x // CHUNK_SIZE, projected.y // CHUNK_SIZE)
        if projected_chunk not in self.explored_tiles:
            unexplored_dirs.append(d)

    chosen_dir = random.choice(
        unexplored_dirs if len(unexplored_dirs) else candidate_dirs
    )
    _move_towards(self, ct, current_pos.add(chosen_dir), DIRECTIONS)


def _manhattan(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


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
            ct.get_entity_type(id) == EntityType.HARVESTER
            and ct.get_team(id) == ct.get_team()
        ):
            self.marker_state.titanium_locations.discard(ct.get_position(id))
            self.marker_state.axionite_locations.discard(ct.get_position(id))
        elif (
            ct.get_entity_type(id) == EntityType.CONVEYOR
            and ct.get_team(id) == ct.get_team()
        ):
            nearby_friendly_conveyors.add(ct.get_position(id))

    self.known_friendly_conveyors.update(nearby_friendly_conveyors)

    self.ore_positions = set(
        list(self.marker_state.titanium_locations)
        + list(self.marker_state.axionite_locations)
    )

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

    self.logger.log("ore locations: {}".format(self.marker_state.titanium_locations))
    self.logger.log("mode: {}".format(self.builder_mode))

    if self.builder_mode == MODE_TILING_BACK:
        current_pos = ct.get_position()
        target_pos = (
            self.return_target_pos
            if self.return_target_pos is not None
            else self.core_pos
        )
        target_kind = self.return_target_kind

        if (
            target_kind == "core"
            and current_pos.distance_squared(target_pos) <= 1
            and not self.pending_build
            and self.harvester_linked
        ):
            self.builder_mode = MODE_FINDING_ORE
            return

        self.logger.log(
            "state: linked {}, pending build {}, return target {}, return target kind {}".format(
                self.harvester_linked,
                self.pending_build,
                self.return_target_pos,
                self.return_target_kind,
            )
        )

        if (
            target_kind == "conveyor"
            and _manhattan(current_pos, target_pos) == 0
            and not self.pending_build
            and self.harvester_linked
        ):
            connect_dir = current_pos.direction_to(target_pos)
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
            self.builder_mode = MODE_FINDING_ORE
            return

        # First turn after building: bridge the gap from the harvester to the bot.
        if not self.harvester_linked:
            # When diagonal, there are exactly 2 cardinal paths to bridge the gap.
            # Try both diagonal options.
            dx = (
                Direction.EAST
                if current_pos.x > self.last_harvester_pos.x
                else (
                    Direction.WEST
                    if current_pos.x < self.last_harvester_pos.x
                    else Direction.CENTRE
                )
            )
            dy = (
                Direction.SOUTH
                if current_pos.y > self.last_harvester_pos.y
                else (
                    Direction.NORTH
                    if current_pos.y < self.last_harvester_pos.y
                    else Direction.CENTRE
                )
            )

            diagonal_options = []
            if (
                dx != Direction.CENTRE and dy != Direction.CENTRE
            ):  # Bot is diagonal from harvester
                # Option 1: go horizontal first
                horiz_dir = dx
                horiz_pos = self.last_harvester_pos.add(dy)
                diagonal_options.append((horiz_pos, horiz_dir))

                # Option 2: go vertical first
                vert_dir = dy
                vert_pos = self.last_harvester_pos.add(dx)
                diagonal_options.append((vert_pos, vert_dir))
            else:
                # Cardinal direction: just one option
                dir_to_bot = self.last_harvester_pos.direction_to(current_pos)
                first_belt_pos = self.last_harvester_pos.add(dir_to_bot)
                diagonal_options.append((first_belt_pos, dir_to_bot))

            # Try to build at one of the diagonal positions
            for belt_pos, belt_dir in diagonal_options:
                if belt_pos != current_pos and ct.can_build_conveyor(
                    belt_pos, belt_dir
                ):
                    self.logger.log(
                        "linking harvester output at {} toward {}".format(
                            belt_pos, current_pos
                        )
                    )
                    self.tiled_back_positions.add(belt_pos)
                    ct.build_conveyor(belt_pos, belt_dir)
                    break

            self.harvester_linked = True
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
        move_dir = _get_bugnav_dir(self, ct, target_pos, CARDINAL_DIRECTIONS)
        if move_dir is not None:
            if not ct.can_build_conveyor(current_pos, move_dir):

                # TODO allow destroying of less useful stuff
                id = ct.get_tile_building_id(current_pos)
                if ct.can_destroy(current_pos) and ct.get_entity_type(id) in [
                    EntityType.MARKER,
                    EntityType.ROAD,
                ]:
                    self.logger.log(
                        "destroying {} at {} to build conveyor toward {}".format(
                            ct.get_entity_type(id), current_pos, move_dir
                        )
                    )
                    ct.destroy(current_pos)

            self.logger.log(
                "tiling back, nearest conveyor distance {}, core distance {}, moving toward {} at {}".format(
                    self.nearest_conveyor_dist_sq,
                    current_pos.distance_squared(self.core_pos),
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
            for pos in list(self.marker_state.titanium_locations):
                d = ct.get_position().distance_squared(pos)
                if all(
                    d <= bot_pos.distance_squared(pos) for bot_pos in self.bot_locations
                ):
                    can_target_ore.append((pos, d))
            can_target_ore.sort(key=lambda x: x[1])

            if len(can_target_ore):
                pos, d = min(can_target_ore, key=lambda x: x[1])

                if ct.can_build_harvester(pos):
                    self.logger.log("building harvester {}".format(pos))
                    ct.build_harvester(pos)
                    self.last_harvester_pos = pos
                    self.harvester_linked = _manhattan(pos, ct.get_position()) == 1
                    self.tiled_back_positions = set()
                    self.nearest_conveyor_pos = None
                    self.nearest_conveyor_dist_sq = float("inf")
                    self.return_target_pos = self.core_pos
                    self.return_target_dist_sq = ct.get_position().distance_squared(
                        self.core_pos
                    )
                    self.return_target_kind = "core"
                    self.bugnav_state = {"bugging": False, "side": 1}
                    self.builder_mode = MODE_TILING_BACK

                    # find suitable target conveyor to connect to after mining the ore

                    visible_candidates = [c for c in self.known_friendly_conveyors]
                    best_target = self.core_pos
                    best_dist = pos.distance_squared(self.core_pos)
                    best_kind = "core"

                    if visible_candidates:
                        nearest_c = min(
                            visible_candidates,
                            key=lambda c_pos: pos.distance_squared(c_pos),
                        )
                        nearest_c_dist = pos.distance_squared(nearest_c)
                        if nearest_c_dist < best_dist:
                            best_target = nearest_c
                            best_dist = nearest_c_dist
                            best_kind = "conveyor"

                    self.return_target_pos = best_target
                    self.return_target_dist_sq = best_dist
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

        # move away from the core
        _move_away_from_core(self, ct)
    else:
        self.logger.print("unknown mode: {}".format(self.builder_mode))
