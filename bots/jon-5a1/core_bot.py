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
ROLE_SEQUENCE = (
    "economy",
    "economy",
    "economy",
    "economy",
    "economy",
    "assault",
    "economy",
    "assault",
    "assault",
    "assault",
)
ASSAULT_SPAWN_DIRECTIONS = [
    direction
    for direction in utils.DIAGONAL_DIRECTIONS
]
ECONOMY_SPAWN_DIRECTIONS = [
    direction
    for direction in utils.CARDINAL_DIRECTIONS
]


class CoreBot:
    def __init__(self):
        self.last_spawn_turn = -SPAWN_BUILDER_INTERVAL_IN_TURNS
        self.logger = None

        # State explicitly owned by the bot
        self.titanium_locations = set()
        self.axionite_locations = set()

        self.builder_counter = 0
        self.assault_spawned = 0
        self.economy_spawned = 0

    def run(self, ct: Controller):
        if self.logger is None:
            self.logger = logger.Logger(ct)

        self._scan_markers(ct)
        self.logger.log(f"ore locations: {self.titanium_locations}")

        if self.builder_counter > MAX_BUILDER_COUNT:
            return

        if self.builder_counter < MIN_BUILDER_COUNT:
            if self._spawn_next_role(ct):
                self.builder_counter += 1
        elif (
            ct.get_current_round() - self.last_spawn_turn
            >= SPAWN_BUILDER_INTERVAL_IN_TURNS
        ):
            if (
                RESOURCE_MIN_SPAWN_BUILDER
                <= ct.get_global_resources()[0]
                <= RESOURCE_MAX_SPAWN_BUILDER
            ):
                if self._spawn_next_role(ct):
                    self.builder_counter += 1
                    self.last_spawn_turn = ct.get_current_round()

    def _scan_markers(self, ct: Controller):
        """Reads nearby markers and updates the bot's internal ore locations state."""
        for id in ct.get_nearby_entities():
            if (
                ct.get_entity_type(id) != EntityType.MARKER
                or ct.get_team(id) != ct.get_team()
            ):
                continue

            ore_report = marker.parse_ore_marker(
                ct.get_marker_value(id), ct.get_map_width(), ct.get_map_height()
            )
            if ore_report is None:
                continue

            ore_pos, _ = ore_report
            self.titanium_locations.add(ore_pos)

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

            if best_dir:
                ore_directions.add(best_dir)

        return list(ore_directions)

    def _next_role(self) -> str:
        if self.builder_counter < len(ROLE_SEQUENCE):
            return ROLE_SEQUENCE[self.builder_counter]
        return "economy"

    def _candidate_directions(self, ct: Controller, role: str):
        pool = ASSAULT_SPAWN_DIRECTIONS if role == "assault" else ECONOMY_SPAWN_DIRECTIONS
        ore_directions = self._get_directions_toward_ore(ct, pool)
        ordered = []
        if ore_directions and random.random() < PROBABILITY_SPAWN_TOWARD_ORE:
            ordered.extend(sorted(ore_directions, key=lambda direction: direction.name))
        ordered.extend(direction for direction in pool if direction not in ordered)
        return ordered

    def _spawn_next_role(self, ct: Controller) -> bool:
        role = self._next_role()
        for direction in self._candidate_directions(ct, role):
            spawn_pos = ct.get_position().add(direction)
            if not ct.can_spawn(spawn_pos):
                continue
            ct.spawn_builder(spawn_pos)
            self.last_spawn_turn = ct.get_current_round()
            if role == "assault":
                self.assault_spawned += 1
            else:
                self.economy_spawned += 1
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

        # Update the bot's state directly
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

        for direction in utils.DIRECTIONS:
            marker_pos = spawn_pos.add(direction)
            if ct.can_place_marker(marker_pos):
                ct.place_marker(marker_pos, marker_value)
                self.logger.print(f"placed marker at {marker_pos}")
                return
