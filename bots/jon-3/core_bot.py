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


class CoreBot:
    def __init__(self):
        self.spawn_directions = utils.DIRECTIONS.copy()
        random.shuffle(self.spawn_directions)

        self.next_spawn_idx = 0
        self.last_spawn_turn = -SPAWN_BUILDER_INTERVAL_IN_TURNS
        self.logger = None

        # State explicitly owned by the bot
        self.titanium_locations = set()
        self.axionite_locations = set()

        self.builder_counter = 0

    def run(self, ct: Controller):
        if self.logger is None:
            self.logger = logger.Logger(ct)

        self._scan_markers(ct)
        self.logger.log(f"ore locations: {self.titanium_locations}")

        if self.builder_counter > MAX_BUILDER_COUNT:
            return

        if self.builder_counter < MIN_BUILDER_COUNT:
            self._spawn_random_around(ct)
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
                self._spawn_random_around(ct)
                self.builder_counter += 1
                self.last_spawn_turn = ct.get_current_round()

    def _scan_markers(self, ct: Controller):
        """Reads nearby markers and updates the bot's internal ore locations state."""
        for id in ct.get_nearby_entities():
            if (
                ct.get_entity_type(id) == EntityType.MARKER
                and ct.get_team(id) == ct.get_team()
            ):
                marker_value = ct.get_marker_value(id)
                positions = marker.parse_ore_marker(
                    marker_value, ct.get_map_width(), ct.get_map_height()
                )
                self.titanium_locations.update(positions)

    def _get_directions_toward_ore(self, ct: Controller):
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

            for direction in self.spawn_directions:
                dot = dx * direction.dx + dy * direction.dy
                if dot > best_dot:
                    best_dot = dot
                    best_dir = direction

            if best_dir:
                ore_directions.add(best_dir)

        return list(ore_directions)

    def _spawn_random_around(self, ct: Controller):
        ore_directions = self._get_directions_toward_ore(ct)

        if ore_directions and random.random() < PROBABILITY_SPAWN_TOWARD_ORE:
            direction = random.choice(ore_directions)
        else:
            direction = self.spawn_directions[self.next_spawn_idx]
            if self.next_spawn_idx == len(self.spawn_directions) - 1:
                self.next_spawn_idx = 0
                random.shuffle(self.spawn_directions)
            else:
                self.next_spawn_idx += 1

        spawn_pos = ct.get_position().add(direction)

        if ct.can_spawn(spawn_pos):
            ct.spawn_builder(spawn_pos)
            self.last_spawn_turn = ct.get_current_round()

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
        for direction in self.spawn_directions:
            marker_pos = spawn_pos.add(direction)

            for id in ct.get_nearby_entities():
                if (
                    ct.get_entity_type(id) == EntityType.MARKER
                    and ct.get_team(id) == ct.get_team()
                ):
                    if ct.get_position(id) == marker_pos and ct.can_destroy(
                        ct.get_position(id)
                    ):
                        ct.destroy(id)

            if ct.can_place_marker(marker_pos):
                ct.place_marker(
                    marker_pos,
                    marker.create_ore_marker(
                        list(self.titanium_locations),  # Pass the state here
                        ct.get_map_width(),
                        ct.get_map_height(),
                    ),
                )
                self.logger.print(f"placed marker at {marker_pos}")
                return
