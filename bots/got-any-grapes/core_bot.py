from cambc import Controller, EntityType, Environment, Position
import random
import marker
import logger
import utils

MIN_BUILDER_COUNT = 4
MAX_BUILDER_COUNT = 12
SPAWN_BUILDER_INTERVAL_IN_TURNS = 12
RESOURCE_MIN_SPAWN_BUILDER = 200
RESOURCE_MAX_SPAWN_BUILDER = 2000
PROBABILITY_SPAWN_TOWARD_ORE = 0.6

OPENING_ASSAULT_SPAWN_ROUNDS = {5, 6}
BONUS_ASSAULT_QUOTA = 3
BONUS_ASSAULT_TITANIUM_THRESHOLD = 90

ASSAULT_SPAWN_DIRECTIONS = [
    utils.direction_toward(Position(0, 0), Position(1, -1)),
    utils.direction_toward(Position(0, 0), Position(-1, -1)),
    utils.direction_toward(Position(0, 0), Position(1, 1)),
    utils.direction_toward(Position(0, 0), Position(-1, 1)),
]
ECONOMY_SPAWN_DIRECTIONS = list(utils.CARDINAL_DIRECTIONS)


class CoreBot:
    def __init__(self):
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
        self.has_connected_economy = False

    def run(self, ct: Controller):
        if self.logger is None:
            self.logger = logger.Logger(ct)

        self._scan_markers(ct)
        self.logger.log(f"ore locations: {self.titanium_locations}")

        # Use live unit count instead of historical spawn count.
        # builder_counter never decrements when units die, so it would
        # permanently cap spawning even when the team has very few units left.
        if ct.get_unit_count() > MAX_BUILDER_COUNT:
            return

        if ct.get_unit_count() < MIN_BUILDER_COUNT:
            if self._spawn_random_around(ct):
                self.builder_counter += 1
            return

        if self._should_force_opening_assault_wave(ct):
            if self._spawn_opening_assault(ct):
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

        if self.assault_spawned < self._assault_quota(ct):
            if self._spawn_bonus_assault(ct):
                self.builder_counter += 1
                self.last_spawn_turn = ct.get_current_round()
                return

        if self._spawn_random_around(ct):
            self.builder_counter += 1
            self.last_spawn_turn = ct.get_current_round()

    def _scan_markers(self, ct: Controller):
        for entity_id in ct.get_nearby_entities():
            if (
                ct.get_entity_type(entity_id) != EntityType.MARKER
                or ct.get_team(entity_id) != ct.get_team()
            ):
                continue

            marker_value = ct.get_marker_value(entity_id)
            ore_report = marker.parse_ore_marker(
                marker_value, ct.get_map_width(), ct.get_map_height()
            )
            if ore_report is not None:
                ore_pos, _ = ore_report
                self.titanium_locations.add(ore_pos)
                continue

            if not self.has_connected_economy:
                cc_report = marker.parse_connected_conveyor_marker(
                    marker_value, ct.get_map_width(), ct.get_map_height()
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

    def _should_force_opening_assault_wave(self, ct: Controller) -> bool:
        return ct.get_current_round() in OPENING_ASSAULT_SPAWN_ROUNDS

    def _assault_quota(self, ct: Controller) -> int:
        if (
            self.has_connected_economy
            and ct.get_global_resources()[0] >= BONUS_ASSAULT_TITANIUM_THRESHOLD
        ):
            return BONUS_ASSAULT_QUOTA
        return len(OPENING_ASSAULT_SPAWN_ROUNDS)

    def _spawn_random_around(self, ct: Controller) -> bool:
        ore_directions = self._get_directions_toward_ore(
            ct, ECONOMY_SPAWN_DIRECTIONS
        )
        if ore_directions and random.random() < PROBABILITY_SPAWN_TOWARD_ORE:
            direction = random.choice(ore_directions)
        else:
            direction = self.economy_spawn_directions[self.economy_spawn_index]
            if self.economy_spawn_index == len(self.economy_spawn_directions) - 1:
                self.economy_spawn_index = 0
                random.shuffle(self.economy_spawn_directions)
            else:
                self.economy_spawn_index += 1

        spawn_pos = ct.get_position().add(direction)
        if ct.can_spawn(spawn_pos):
            ct.spawn_builder(spawn_pos)
            self.last_spawn_turn = ct.get_current_round()
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
        for pos in ct.get_nearby_tiles():
            if (
                ct.get_tile_env(pos) == Environment.ORE_AXIONITE
                or ct.get_tile_env(pos) == Environment.ORE_TITANIUM
            ):
                titanium_locations_tmp.append(
                    (ct.get_position().distance_squared(pos), pos)
                )

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
