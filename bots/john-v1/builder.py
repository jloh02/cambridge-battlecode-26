from cambc import (
    Controller,
    Direction,
    EntityType,
    Enum,
    Position,
    Environment,
    GameConstants,
)
import random
import constants
import marker
import logger


class BuilderMode(Enum):
    EXPLORE = 1
    BUILD_HARVESTER = 2


class Builder:
    def __init__(self, ct: Controller):
        self.core_position: Position | None = None
        self.mode: BuilderMode = BuilderMode.EXPLORE
        self.marker_state: marker.MarkerState = marker.MarkerState()

    def _build_harvester_if_possible(self, ct: Controller):
        """Attempts to build a harvester on an adjacent ore tile."""
        for d in Direction:
            check_pos = ct.get_position().add(d)
            if ct.can_build_harvester(check_pos):
                ct.build_harvester(check_pos)
                break

    def run(self, ct: Controller):
        # if we are adjacent to an ore tile, build a harvester on it
        self._build_harvester_if_possible(ct)

        # move in a random direction
        move_dir = random.choice(constants.DIRECTIONS)
        move_pos = ct.get_position().add(move_dir)
        # we need to place a conveyor or road to stand on, before we can move onto a tile
        if ct.can_build_road(move_pos):
            ct.build_road(move_pos)
        if ct.can_move(move_dir):
            ct.move(move_dir)

        # # place a marker on an adjacent tile with the current round number
        # marker_pos = ct.get_position().add(random.choice(constants.DIRECTIONS))
        # if ct.can_place_marker(marker_pos):
        #     ct.place_marker(marker_pos, ct.get_current_round())
