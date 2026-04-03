from cambc import Controller, EntityType, Environment, Position
import random
import marker
import logger
import utils

MIN_BUILDER_COUNT = 4
MAX_BUILDER_COUNT = 10
SPAWN_BUILDER_INTERVAL_IN_TURNS = 15
RESOURCE_MIN_SPAWN_BUILDER = 500
RESOURCE_MAX_SPAWN_BUILDER = 2000
PROBABILITY_SPAWN_TOWARD_ORE = 0.6

MIN_CONNECTED_LANES_FOR_BONUS_ASSAULT = 3  # Potentially unused; retained for future lane-aware tuning.
INITIAL_ASSAULT_QUOTA = 2
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
        self.assault_quota = 0
        self.assault_spawned = 0
        self.used_assault_directions = set()

    def run(self, ct: Controller):
        if self.logger is None:
            self.logger = logger.Logger(ct)

        self._scan_markers(ct)
        self.assault_quota = self._current_assault_quota(ct)
        self.logger.log(
            "economy"
            + f" assault_quota={self.assault_quota}"
            + f" assault_spawned={self.assault_spawned}"
        )

        if self.builder_counter > MAX_BUILDER_COUNT:
            return

        if self.builder_counter < MIN_BUILDER_COUNT:
            if self._spawn_next_role(ct, force_role="economy"):
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

        if self._spawn_next_role(ct):
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

    def _current_assault_quota(self, ct: Controller) -> int:
        quota = INITIAL_ASSAULT_QUOTA
        if ct.get_global_resources()[0] >= BONUS_ASSAULT_TITANIUM_THRESHOLD:
            quota = BONUS_ASSAULT_QUOTA
        return quota

    def _next_role(self, ct: Controller) -> str:
        if self.assault_spawned < self._current_assault_quota(ct):
            return "assault"
        return "economy"

    def _candidate_directions(self, ct: Controller, role: str):
        if role == "assault":
            unused = [
                direction
                for direction in ASSAULT_SPAWN_DIRECTIONS
                if direction not in self.used_assault_directions
            ]
            return unused or ASSAULT_SPAWN_DIRECTIONS

        ore_directions = self._get_directions_toward_ore(ct, ECONOMY_SPAWN_DIRECTIONS)
        ordered = []
        if ore_directions and random.random() < PROBABILITY_SPAWN_TOWARD_ORE:
            ordered.extend(sorted(ore_directions, key=lambda direction: direction.name))

        rotated = (
            self.economy_spawn_directions[self.economy_spawn_index :]
            + self.economy_spawn_directions[: self.economy_spawn_index]
        )
        self.economy_spawn_index = (
            self.economy_spawn_index + 1
        ) % len(self.economy_spawn_directions)
        for direction in rotated:
            if direction not in ordered:
                ordered.append(direction)
        return ordered

    def _spawn_next_role(self, ct: Controller, force_role: str | None = None) -> bool:
        role = force_role or self._next_role(ct)
        for direction in self._candidate_directions(ct, role):
            spawn_pos = ct.get_position().add(direction)
            if not ct.can_spawn(spawn_pos):
                continue

            ct.spawn_builder(spawn_pos)
            self.last_spawn_turn = ct.get_current_round()
            if role == "assault":
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
