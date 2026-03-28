from cambc import (
    Controller,
    Direction,
    EntityType,
    Environment,
    Position,
)
import random
import constants
import marker
import logger


class Core:
    def __init__(self, ct: Controller):
        self.num_spawned = 0  # number of builder bots spawned so far (core)
        self.marker_state: marker.MarkerState = marker.MarkerState()

    def run(self, ct: Controller):
        if self.num_spawned < 4:
            # if we haven't spawned 4 builder bots yet, try to spawn one on a random tile
            spawn_pos = ct.get_position().add(random.choice(constants.DIRECTIONS))
            if ct.can_spawn(spawn_pos):
                ct.spawn_builder(spawn_pos)
                self.num_spawned += 1
