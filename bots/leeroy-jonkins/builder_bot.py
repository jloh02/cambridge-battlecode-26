from cambc import Controller, EntityType
from states import BuilderMode, TargetKind
import logger
import perception
import mode_exploring
import mode_finding_ore
import mode_rush
import mode_tiling_back
import healing
import utils
import time

SOFT_DECISION_DEADLINE_NANOSECONDS = 1_800_000

class BuilderBot:
    def __init__(self):
        self.core_pos = None
        self.logger = None
        # Same strategy as `jon-5`, cheaper execution: every builder keeps a
        # soft internal deadline below the real 2 ms cap so pathfinding can
        # refuse expensive replans before the turn is already in danger.
        self.turn_started_ns = 0
        self.turn_decision_deadline_ns = 0
        self.last_full_perception_round = -1

        # Start in FINDING_ORE mode
        self.builder_mode = BuilderMode.FINDING_ORE

        # This is the builder's private long-lived world model. Nothing here is
        # shared across units except through explicit marker traffic.
        # --- Master Map ---
        self.grid = (
            {}
        )  # (x, y) -> {'env': Environment, 'entity': EntityType, 'team': int, ...}

        # Per-turn perception refreshes these derived caches from the remembered
        # grid so the mode logic can stay focused on strategy decisions.
        # --- Inferred State (Populated by perception) ---
        self.titanium_locations = set()
        self.axionite_locations = set()
        self.bot_locations = set()
        self.known_friendly_conveyors = set()
        self.connected_friendly_conveyors = {}
        self.pathfinding_state = {
            "known_obstacles": set(),
            "path": [],
            "temporary_obstacles": {},
            "current_target": None,
            "last_obstacle_signature": None,
            "last_replan_signature": None,
            "last_replan_round": -1,
        }

        # Exploration is intentionally coarse: it spreads builders through fog
        # without trying to solve a full team-global scouting problem.
        # --- Exploration State ---
        self.explored_tiles = set()
        self.all_map_chunks = None
        self.explore_target_chunk = None
        self.explore_target_pos = None
        self.claimed_explore_chunks = set()
        self.shared_ore_positions = set()
        self.shared_connected_conveyor_positions = set()

        # TILING_BACK is the bot's main differentiator: it remembers enough lane
        # state to finish a working delivery route instead of just finding ore.
        # --- Tiling State ---
        self.last_harvester_pos = None
        self.tiled_back_positions = set()
        self.pending_build = None
        self.nearest_conveyor_pos = None
        self.nearest_conveyor_dist_manhatten = float("inf")
        self.return_target_pos = None
        self.return_target_dist_manhatten = float("inf")
        self.return_target_kind = TargetKind.CORE
        self.last_return_target_refresh_round = -1
        self.pending_bridge_plan = None
        self.bridge_transit_cooldown_until = -1

        # Harvester tracking: keeps track of harvesters and their connectivity
        # Maps harvester position tuple to {'adjacent_conveyors': int, 'claimed_by_us': bool}
        self.known_harvesters = {}  # (x, y) -> info dict
        self.claimed_harvesters = (
            set()
        )  # Set of (x, y) tuples for our own claimed harvesters

        self.stats = {
            "astar_calls": 0,
            "astar_cache_hits": 0,
            "astar_recomputes": 0,
            "astar_timeout_exits": 0,
            "astar_iteration_exits": 0,
            "astar_best_effort": 0,
            "astar_nodes_expanded": 0,
            "astar_open_set_peak": 0,
            "path_invalid_target": 0,
            "path_invalid_known": 0,
            "path_invalid_temp": 0,
            "path_trimmed": 0,
            "double_astar_turns": 0,
            "greedy_fallback_used": 0,
            "micro_plan_used": 0,
            "astar_budget_skips": 0,
            "fast_perception_turns": 0,
        }
        self.turn_timing = {
            "perception_ns": 0,
            "mode_ns": 0,
            "turn_ns": 0,
        }
        self.last_connected_refresh_round = -1

        # Opening-role assignment
        self.is_rush_builder = False

        # --- RUSH State ---
        self.rush_target_core_pos = None
        self.rush_hijack_pos = None
        self.rush_build_stance = None
        self.rush_turret_type = None
        self.rush_turret_direction = None
        self.rush_symmetry_candidates = None
        self.rush_failed_candidates = set()
        self.rush_turret_built = False

    def _init_turn(self, ct: Controller):
        if self.logger is None:
            self.logger = logger.Logger(ct)

        if self.core_pos is not None:
            return

        my_team = ct.get_team()

        for unit_id in ct.get_nearby_units():
            if ct.get_entity_type(unit_id) != EntityType.CORE:
                continue
            if ct.get_team(unit_id) != my_team:
                continue
            self.core_pos = ct.get_position(unit_id)
            return
    
    def _should_use_fast_perception(self, ct: Controller) -> bool:
        # The local-only fast scan is kept disabled until it also preserves
        # full-vision adversary awareness. This timing pass is focused on
        # cheaper full scans first, not narrower scans.
        return False

    def _bum_rush(self, ct: Controller):

        if self.is_rush_builder:
            return

        if self.core_pos is None:
            # This should never happen. Fix by locating the core again.
            self.logger.log("ERROR: Core position not found!")
            self._init_turn(ct)
            return

        rush_spawn_pos = mode_rush.get_rush_spawn_pos(ct, self.core_pos)
        if ct.get_position() == rush_spawn_pos:
            self.is_rush_builder = True
            self.builder_mode = BuilderMode.RUSH
            self.logger.log("Assigned opening RUSH role")
        
    def stop_rushing(self):
        '''
        This is called when the bot is done rushing and should transition back to normal builder behavior. 
        It resets all rush-specific state so the bot can cleanly switch modes.
        '''
        if not self.is_rush_builder:
            return
        
        self.builder_mode = BuilderMode.EXPLORING
        self.is_rush_builder = False
        self.rush_hijack_pos = None
        self.rush_build_stance = None
        self.rush_turret_type = None
        self.rush_turret_direction = None
        self.rush_symmetry_candidates = None
        self.rush_failed_candidates = set()
        self.rush_turret_built = False
        self.rush_target_core_pos = None

    def run(self, ct: Controller):
        turn_start = time.time_ns()
        self.turn_started_ns = turn_start
        self.turn_decision_deadline_ns = turn_start + SOFT_DECISION_DEADLINE_NANOSECONDS
        self._init_turn(ct)

        # Build map and infer state
        p_start = time.time_ns() if utils.DEBUG else 0
        use_fast_perception = self._should_use_fast_perception(ct)
        perception.scan_around(self, ct, fast=use_fast_perception)
        if use_fast_perception:
            self.stats["fast_perception_turns"] += 1
        else:
            self.last_full_perception_round = ct.get_current_round()
        if utils.DEBUG:
            self.turn_timing["perception_ns"] = time.time_ns() - p_start
        self._bum_rush(ct)

        self.logger.log(f"mode: {self.builder_mode.name}")
        self.logger.log("Locations - Titanium: " + str(self.titanium_locations))
        self.logger.log("Locations - Axionite: " + str(self.axionite_locations))

        # Global pre-emption: outside TILING_BACK, prioritize defensive heals
        # before ore/exploration decisions.
        if self.builder_mode not in {BuilderMode.TILING_BACK, BuilderMode.RUSH}:
            if healing.preemptive_heal_or_move(self, ct):
                if utils.DEBUG:
                    self.turn_timing["mode_ns"] = 0
                    self.turn_timing["turn_ns"] = time.time_ns() - turn_start
                return

        # State Transition: Stop exploring if ore is found
        if self.builder_mode == BuilderMode.EXPLORING and len(self.titanium_locations):
            self.builder_mode = BuilderMode.FINDING_ORE
            self.explore_target_chunk = None
            self.explore_target_pos = None

        # Execute Current State
        m_start = time.time_ns() if utils.DEBUG else 0
        if self.builder_mode == BuilderMode.TILING_BACK:
            mode_tiling_back.execute(self, ct)
        elif self.builder_mode == BuilderMode.RUSH:
            mode_rush.execute(self, ct)
        elif self.builder_mode == BuilderMode.FINDING_ORE:
            mode_finding_ore.execute(self, ct)
        elif self.builder_mode == BuilderMode.EXPLORING:
            mode_exploring.execute(self, ct)
        else:
            self.logger.print(f"unknown mode: {self.builder_mode.name}")

        if utils.DEBUG:
            self.turn_timing["mode_ns"] = time.time_ns() - m_start
            self.turn_timing["turn_ns"] = time.time_ns() - turn_start

            round_num = ct.get_current_round()
            if round_num % 25 == 0:
                self.logger.log(
                    "perf"
                    + f" turn={self.turn_timing['turn_ns'] / 1_000_000:.2f}ms"
                    + f" perception={self.turn_timing['perception_ns'] / 1_000_000:.2f}ms"
                    + f" mode={self.turn_timing['mode_ns'] / 1_000_000:.2f}ms"
                    + f" a*calls={self.stats['astar_calls']}"
                    + f" cache_hits={self.stats['astar_cache_hits']}"
                    + f" recomputes={self.stats['astar_recomputes']}"
                    + f" timeouts={self.stats['astar_timeout_exits']}"
                    + f" best_effort={self.stats['astar_best_effort']}"
                    + f" fallback={self.stats['greedy_fallback_used']}"
                    + f" micro={self.stats['micro_plan_used']}"
                    + f" budget_skips={self.stats['astar_budget_skips']}"
                    + f" double_astar={self.stats['double_astar_turns']}"
                    + f" fast_scan={self.stats['fast_perception_turns']}"
                )
