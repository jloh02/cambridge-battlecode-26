from cambc import Controller, EntityType
from states import BuilderMode, TargetKind
import logger
import perception
import mode_exploring
import mode_finding_ore
import mode_tiling_back


class BuilderBot:
    def __init__(self):
        self.core_pos = None
        self.logger = None

        # Start in FINDING_ORE mode
        self.builder_mode = BuilderMode.FINDING_ORE

        # --- Master Map ---
        self.grid = (
            {}
        )  # (x, y) -> {'env': Environment, 'entity': EntityType, 'team': int, ...}

        # --- Inferred State (Populated by perception) ---
        self.titanium_locations = set()
        self.axionite_locations = set()
        self.bot_locations = set()
        self.known_friendly_conveyors = set()
        self.pathfinding_state = {"known_obstacles": set(), "path": []}

        # --- Exploration State ---
        self.explored_tiles = set()
        self.all_map_chunks = None
        self.explore_target_chunk = None
        self.explore_target_pos = None

        # --- Tiling State ---
        self.last_harvester_pos = None
        self.tiled_back_positions = set()
        self.pending_build = None
        self.nearest_conveyor_pos = None
        self.nearest_conveyor_dist_manhatten = float("inf")
        self.return_target_pos = None
        self.return_target_dist_manhatten = float("inf")
        self.return_target_kind = TargetKind.CORE
        self.bridge_transit_path = None

    def _init_turn(self, ct: Controller):
        if self.logger is None:
            self.logger = logger.Logger(ct)

        if self.core_pos is None:
            cores = [
                id
                for id in ct.get_nearby_entities()
                if ct.get_entity_type(id) == EntityType.CORE
            ]
            if cores:
                self.core_pos = ct.get_position(cores[0])

    def run(self, ct: Controller):
        self._init_turn(ct)

        # Build map and infer state
        perception.scan_around(self, ct)

        # State Transition: Stop exploring if ore is found
        if self.builder_mode == BuilderMode.EXPLORING and len(self.titanium_locations):
            self.builder_mode = BuilderMode.FINDING_ORE
            self.explore_target_chunk = None
            self.explore_target_pos = None

        self.logger.log(f"mode: {self.builder_mode.name}")
        self.logger.log("Locations - Titanium: " + str(self.titanium_locations))
        self.logger.log("Locations - Axionite: " + str(self.axionite_locations))

        # Execute Current State
        if self.builder_mode == BuilderMode.TILING_BACK:
            mode_tiling_back.execute(self, ct)
        elif self.builder_mode == BuilderMode.FINDING_ORE:
            mode_finding_ore.execute(self, ct)
        elif self.builder_mode == BuilderMode.EXPLORING:
            mode_exploring.execute(self, ct)
        else:
            self.logger.print(f"unknown mode: {self.builder_mode.name}")
