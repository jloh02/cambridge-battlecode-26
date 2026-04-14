from cambc import Controller, Direction, EntityType, Environment, Position
import random
import marker
import logger
import utils

MIN_BUILDER_COUNT = 4
MAX_BUILDER_COUNT = 16
SPAWN_BUILDER_INTERVAL_IN_TURNS = 8
RESOURCE_MIN_SPAWN_BUILDER = 200
RESOURCE_MAX_SPAWN_BUILDER = 10000
PROBABILITY_SPAWN_TOWARD_ORE = 0.6

# Opening contract: Builder -> Builder -> Builder -> Core Defender -> Rusher.
# Directions are expressed in a seat-agnostic frame from our core toward the
# physical map center. The first three builders use the three non-inward
# cardinal slots in a seeded random order, the defender uses the inward
# cardinal slot, and the rusher uses the diagonal pointing toward the symmetry
# core candidate.
OPENING_ROLE_SEQUENCE = ("BUILDER", "BUILDER", "BUILDER", "DEFENDER", "RUSHER")
OPENING_BUILDER_COUNT = 3

ASSAULT_SPAWN_DIRECTIONS = [
    utils.direction_toward(Position(0, 0), Position(1, -1)),
    utils.direction_toward(Position(0, 0), Position(-1, -1)),
    utils.direction_toward(Position(0, 0), Position(1, 1)),
    utils.direction_toward(Position(0, 0), Position(-1, 1)),
]
ECONOMY_SPAWN_DIRECTIONS = list(utils.CARDINAL_DIRECTIONS)

# The first 4 builders all spawn on cardinal slots. The 4th slot is the
# SYMMETRY-AWARE DEFENDER — whichever cardinal direction points from our
# core toward the map center. This fixes the seat bias observed in
# previous runs: the old fixed `EAST` defender was toward-center for
# TEAM_A (upper-left core) but toward-edge for TEAM_B (lower-right core)
# on rotation-symmetric maps. The new centerward defender puts the
# sentinel-building role between us and the likely enemy approach,
# restoring the seat-A/seat-B symmetry.
#
# `_compute_role_spawn_order(ct)` is called in `_spawn_random_around` to
# produce a per-game (NORTH, SOUTH, WEST, EAST)-like sequence with the
# centerward cardinal moved to slot 4. The three non-defender cardinals
# are plain ore finders (no additional roles).
_ALL_CARDINALS = (
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
)


class CoreBot:
    def __init__(self):
        # Deterministic-seed opt-in for benchmark repeatability. When
        # `utils.USE_GLOBAL_SEED` is True we re-seed Python's `random`
        # module from the cambc game seed parsed out of `sys.argv`
        # (the cambc CLI passes `--seed <int>` through to the bot
        # subprocess). Same game seed -> same spawn-rotation shuffle
        # AND same `random.random() < ore_bias` outcomes across
        # repeated benchmark runs of the same bot code; different
        # seeds still vary so the rotation is not pinned to one fixed
        # order. This is OFF by default — deployed bots stay
        # non-deterministic so a remote opponent cannot fingerprint
        # and exploit a known rotation.
        if utils.USE_GLOBAL_SEED:
            seed_value = utils.GLOBAL_SEED_VALUE
            if seed_value is None:
                seed_value = utils.cambc_game_seed_from_argv()
            if seed_value is not None:
                random.seed(seed_value)
        self.economy_spawn_directions = ECONOMY_SPAWN_DIRECTIONS.copy()
        random.shuffle(self.economy_spawn_directions)
        self.economy_spawn_index = 0
        self.last_spawn_turn = -SPAWN_BUILDER_INTERVAL_IN_TURNS
        self.logger = None

        self.titanium_locations = set()
        self.axionite_locations = set()

        self.builder_counter = 0
        self.assault_spawned = 0
        self.used_assault_directions = set()
        self.opening_builder_directions = None
        self.used_opening_directions = set()
        self.has_connected_economy = False

    def run(self, ct: Controller):
        if self.logger is None:
            self.logger = logger.Logger(ct)

        self._scan_markers(ct)
        if utils.DEBUG:
            self.logger.log(f"ore locations: {self.titanium_locations}")

        # Use live unit count instead of historical spawn count.
        # builder_counter never decrements when units die, so it would
        # permanently cap spawning even when the team has very few units left.
        if ct.get_unit_count() > MAX_BUILDER_COUNT:
            return

        # Open with the explicit role contract. `builder_counter` counts only
        # successful builder spawns, so temporary core-shell blocking delays
        # the role rather than silently changing it.
        if self.builder_counter < len(OPENING_ROLE_SEQUENCE):
            if self._spawn_opening_role(ct):
                self.builder_counter += 1
            return

        if (
            ct.get_current_round() - self.last_spawn_turn
            < SPAWN_BUILDER_INTERVAL_IN_TURNS
        ):
            return

        if not (
            RESOURCE_MIN_SPAWN_BUILDER
            <= ct.get_global_resources()[0]
            <= RESOURCE_MAX_SPAWN_BUILDER
        ):
            return

        if self._spawn_random_around(ct):
            self.builder_counter += 1
            self.last_spawn_turn = ct.get_current_round()

    def _scan_markers(self, ct: Controller):
        my_team = ct.get_team()
        map_width = None
        map_height = None
        for entity_id in ct.get_nearby_entities():
            entity_type = ct.get_entity_type(entity_id)
            if entity_type != EntityType.MARKER:
                continue
            if ct.get_team(entity_id) != my_team:
                continue

            marker_value = ct.get_marker_value(entity_id)
            if map_width is None:
                map_width = ct.get_map_width()
                map_height = ct.get_map_height()
            ore_report = marker.parse_ore_marker(
                marker_value, map_width, map_height
            )
            if ore_report is not None:
                ore_pos, _ = ore_report
                self.titanium_locations.add(ore_pos)
                continue

            if not self.has_connected_economy:
                cc_report = marker.parse_connected_conveyor_marker(
                    marker_value, map_width, map_height
                )
                if cc_report is not None:
                    self.has_connected_economy = True

    def _get_directions_toward_ore(self, ct: Controller, spawn_directions):
        if not self.titanium_locations:
            return []

        core_pos = ct.get_position()
        ore_directions = set()

        for ore_pos in self.titanium_locations:
            dx = ore_pos.x - core_pos.x
            dy = ore_pos.y - core_pos.y

            if dx == 0 and dy == 0:
                continue

            best_dir = None
            best_dot = -float("inf")
            for direction in spawn_directions:
                ddx, ddy = direction.delta()
                dot = dx * ddx + dy * ddy
                if dot > best_dot:
                    best_dot = dot
                    best_dir = direction

            if best_dir is not None:
                ore_directions.add(best_dir)

        return list(ore_directions)

    def _assault_quota(self, ct: Controller) -> int:
        return 0

    def _centerward_cardinal(self, ct: Controller) -> Direction:
        return self._opening_orientation_frame(ct)["inward"]

    def _opening_orientation_frame(self, ct: Controller) -> dict[str, Direction]:
        return utils.physical_center_orientation(
            ct.get_position(),
            ct.get_map_width(),
            ct.get_map_height(),
        )

    def _role_spawn_order(self, ct: Controller) -> tuple:
        defender = self._centerward_cardinal(ct)
        others = tuple(d for d in _ALL_CARDINALS if d != defender)
        return others + (defender,)

    def _opening_builder_spawn_directions(self, ct: Controller) -> list[Direction]:
        if self.opening_builder_directions is not None:
            return self.opening_builder_directions

        frame = self._opening_orientation_frame(ct)
        preferred = [
            frame["secondary"],
            frame["opposite_secondary"],
            frame["outward"],
        ]
        random.shuffle(preferred)
        # Edge/corner cores can have one or two non-inward cardinals off-map.
        # Keep the first three roles as builders by falling back to any
        # non-defender/non-rusher adjacent spawn tile; BuilderBot classifies
        # those fallback offsets as ordinary builders during the opening
        # window.
        fallback = [
            direction
            for direction in utils.DIRECTIONS
            if direction not in preferred
            and direction != frame["inward"]
            and direction != frame["rusher"]
        ]
        random.shuffle(fallback)
        directions = preferred + fallback
        self.opening_builder_directions = directions
        return directions

    def _opening_role_directions(self, ct: Controller, role: str) -> list[Direction]:
        frame = self._opening_orientation_frame(ct)
        if role == "DEFENDER":
            return [frame["inward"]]
        if role == "RUSHER":
            return [frame["rusher"]]

        directions = [
            direction
            for direction in self._opening_builder_spawn_directions(ct)
            if direction not in self.used_opening_directions
        ]
        return directions

    def _spawn_opening_role(self, ct: Controller) -> bool:
        role = OPENING_ROLE_SEQUENCE[self.builder_counter]
        core_pos = ct.get_position()
        for direction in self._opening_role_directions(ct, role):
            spawn_pos = core_pos.add(direction)
            if not ct.can_spawn(spawn_pos):
                continue
            ct.spawn_builder(spawn_pos)
            self.used_opening_directions.add(direction)
            self.last_spawn_turn = ct.get_current_round()
            if role == "RUSHER":
                self.assault_spawned += 1
            return True
        return False

    def _spawn_random_around(self, ct: Controller) -> bool:
        ore_directions = self._get_directions_toward_ore(
            ct, ECONOMY_SPAWN_DIRECTIONS
        )
        # Build a prioritized candidate list: ore-biased directions first,
        # then fallback through the full economy rotation.
        candidates = []
        if ore_directions and random.random() < PROBABILITY_SPAWN_TOWARD_ORE:
            candidates.extend(ore_directions)

        # Append remaining economy directions in rotation order
        for i in range(len(self.economy_spawn_directions)):
            idx = (self.economy_spawn_index + i) % len(self.economy_spawn_directions)
            d = self.economy_spawn_directions[idx]
            if d not in candidates:
                candidates.append(d)

        for direction in candidates:
            spawn_pos = ct.get_position().add(direction)
            if ct.can_spawn(spawn_pos):
                ct.spawn_builder(spawn_pos)
                self.last_spawn_turn = ct.get_current_round()
                # Advance rotation index past the used direction
                try:
                    used_idx = self.economy_spawn_directions.index(direction)
                    self.economy_spawn_index = (used_idx + 1) % len(self.economy_spawn_directions)
                except ValueError:
                    pass
                return True
        return False

    def _spawn_opening_assault(self, ct: Controller) -> bool:
        return self._spawn_assault(ct)

    def _spawn_bonus_assault(self, ct: Controller) -> bool:
        return self._spawn_assault(ct)

    def _spawn_assault(self, ct: Controller) -> bool:
        ordered_directions = [
            direction
            for direction in ASSAULT_SPAWN_DIRECTIONS
            if direction not in self.used_assault_directions
        ] or ASSAULT_SPAWN_DIRECTIONS

        for direction in ordered_directions:
            spawn_pos = ct.get_position().add(direction)
            if not ct.can_spawn(spawn_pos):
                continue

            ct.spawn_builder(spawn_pos)
            self.assault_spawned += 1
            self.used_assault_directions.add(direction)
            return True
        return False

    def _get_titanium_locations_in_priority_order(self, ct: Controller):
        titanium_locations_tmp = []
        core_pos = ct.get_position()
        for pos in ct.get_nearby_tiles():
            env = ct.get_tile_env(pos)
            if env == Environment.ORE_AXIONITE or env == Environment.ORE_TITANIUM:
                titanium_locations_tmp.append((core_pos.distance_squared(pos), pos))

        ordered_locations = list(
            map(lambda x: x[1], sorted(titanium_locations_tmp, key=lambda x: x[0]))
        )
        self.titanium_locations.update(ordered_locations)

    def _place_marker_direction_around(self, ct: Controller, spawn_pos: Position):
        if not self.titanium_locations:
            return

        ore_pos = min(
            self.titanium_locations,
            key=lambda pos: spawn_pos.distance_squared(pos),
        )
        marker_value = marker.create_ore_marker(
            ore_pos, ct.get_current_round(), ct.get_map_width(), ct.get_map_height()
        )

        for direction in self.economy_spawn_directions:
            marker_pos = spawn_pos.add(direction)
            if ct.can_place_marker(marker_pos):
                ct.place_marker(marker_pos, marker_value)
                self.logger.print(f"placed marker at {marker_pos}")
                return
