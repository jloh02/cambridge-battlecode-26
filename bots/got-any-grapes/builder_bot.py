from cambc import Controller, EntityType
from states import BuilderMode, TargetKind
import logger
import mode_assaulting
import perception
import mode_exploring
import mode_finding_ore
import mode_hijacking
import mode_tiling_back
import healing
import timing
import utils
import time

SOFT_DECISION_DEADLINE_NANOSECONDS = timing.SOFT_DECISION_BUDGET_NS
# Assault builders now stay on the cheap local scan by default and only pay
# for a full refresh on a periodic heartbeat or after they leave the spawn
# bootstrap shell.
ASSAULT_FULL_PERCEPTION_INTERVAL = 6
ECON_OPENING_UNCLOG_MAX_ROUND = 18
SYMMETRY_MODES = ("ROT180", "MIRROR_X", "MIRROR_Y")


class BuilderBot:
    def __init__(self):
        self.core_pos = None
        self.logger = None
        self.turn_started_ns = 0
        self.turn_decision_deadline_ns = 0
        self.turn_hard_deadline_ns = 0
        self.timing_governor = None
        self.last_full_perception_round = -1

        self.builder_mode = BuilderMode.FINDING_ORE
        self.spawn_pos = None
        self.spawn_slot = None
        self.is_assault_role = None

        self.grid = {}

        self.titanium_locations = set()
        self.axionite_locations = set()
        self.ore_target_blacklist = {}
        self.ore_target_state = {
            "ore": None,
            "access": None,
            "stuck_turns": 0,
        }
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

        self.explored_tiles = set()
        self.explored_chunk_last_seen = {}
        self.all_map_chunks = None
        self.explore_target_chunk = None
        self.explore_target_pos = None
        self.claimed_explore_chunks = set()
        self.claimed_assault_anchor_keys = set()
        self.shared_ore_positions = set()
        self.shared_connected_conveyor_positions = set()
        self.shared_connected_harvester_positions = set()

        self.last_harvester_pos = None
        self.tiled_back_positions = set()
        self.pending_build = None
        self.nearest_conveyor_pos = None
        self.nearest_conveyor_dist_manhatten = float("inf")
        self.return_target_pos = None
        self.return_target_dist_manhatten = float("inf")
        self.return_target_kind = TargetKind.CORE
        self.last_return_target_refresh_round = -1
        self.bridge_transit_path = None
        self.pending_bridge_plan = None
        self.bridge_transit_cooldown_until = -1
        self.known_harvesters = {}
        self.claimed_harvesters = set()
        self.hijack_source_pos = None
        self.hijack_entry_pos = None
        self.tiling_back_origin_kind = "HARVESTER"

        self.enemy_core_anchor = None
        self.enemy_core_exact = False
        self.last_enemy_core_position = None
        self.world_orientation = None
        self.world_orientation_last_round = -9999
        self.symmetry_candidates = SYMMETRY_MODES
        self.best_symmetry_mode = None
        self.symmetry_confidence = "LOW"
        self.last_symmetry_update_round = -9999
        self.symmetry_tile_cache = None
        self.symmetry_tile_cache_count = -1
        self.confirmed_enemy_harvesters = {}
        self.predicted_enemy_harvesters = []
        self.discovery_turns_without_new_ore = 0
        self.assault_known_ore_count = 0
        self.harvester_anchor = None
        self.harvester_anchor_last_seen_round = -9999
        self.assault_anchor_blacklist = {}
        self.assault_anchor_status = None
        self.assault_last_site_signature = None
        self.assault_subrole = "scout"
        self.assault_last_progress_round = -9999
        self.visible_enemy_targets = []
        self.visible_enemy_passable_buildings = set()
        self.visible_friendly_builders = []
        self.recent_assault_waypoints = {}
        self.assault_exhausted_regions = []
        self.assault_exhausted_sectors = {}
        self.assault_scout_state = {
            "target": None,
            "chunk": None,
            "anchor": None,
            "expires_round": -1,
        }
        self.assault_claim_state = {
            "anchor": None,
            "last_round": -9999,
        }
        self.assault_bootstrap_state = {
            "target": None,
            "path": [],
            "expires_round": -1,
            "blocked_turns": 0,
        }
        self.assault_opening_escape_complete = False
        self.assault_execute_state = {
            "subplan": None,
            "anchor": None,
            "ring": None,
            "direction": None,
            "wait_turns": 0,
            "fire_wait_turns": 0,
            "clear_attempts": 0,
        }
        self.assault_committed_site = None
        self.assault_committed_site_round = -9999
        self.assault_frontier_reset_state = {
            "anchor": None,
            "last_round": -9999,
            "count": 0,
        }
        self.assault_nav_failure_count = 0
        self.assault_progress_stall_count = 0
        self.assault_best_dist_to_ring = 9999
        self.assault_nav_progress_target = None
        self.assault_nav_state = {
            "current_target": None,
            "bfs_path": [],
            "frontier_target": None,
        }

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
            "assault_bfs_replans": 0,
            "assault_bfs_cache_hits": 0,
        }
        self.turn_timing = {
            "perception_ns": 0,
            "mode_ns": 0,
            "turn_ns": 0,
        }
        self.turn_profile = None
        self.last_assault_profile_ring_key = None
        self.last_connected_refresh_round = -1

    def _init_turn(self, ct: Controller):
        if self.logger is None:
            self.logger = logger.Logger(ct)
        if self.spawn_pos is None:
            self.spawn_pos = ct.get_position()

        if self.core_pos is None:
            cores = [
                entity_id
                for entity_id in ct.get_nearby_entities()
                if ct.get_entity_type(entity_id) == EntityType.CORE
            ]
            if cores:
                self.core_pos = ct.get_position(cores[0])

        if self.core_pos is not None and self.spawn_pos is not None and self.spawn_slot is None:
            dx = self.spawn_pos.x - self.core_pos.x
            dy = self.spawn_pos.y - self.core_pos.y
            role_map = {
                (1, -1): 0,
                (-1, -1): 1,
                (1, 1): 2,
                (-1, 1): 3,
            }
            self.spawn_slot = role_map.get((dx, dy))

        if self.is_assault_role is None:
            self.is_assault_role = self.spawn_slot is not None
            if self.is_assault_role:
                self.builder_mode = BuilderMode.ASSAULTING
                self.assault_last_progress_round = ct.get_current_round()

    def _should_use_fast_perception(self, ct: Controller) -> bool:
        if not self.is_assault_role:
            return False

        if mode_assaulting.opening_escape_active(self, ct):
            return True

        if self.last_full_perception_round < 0:
            return False

        return (
            ct.get_current_round() - self.last_full_perception_round
            < ASSAULT_FULL_PERCEPTION_INTERVAL
        )

    def run(self, ct: Controller):
        turn_start = time.time_ns()
        self.timing_governor = timing.TimingGovernor.start_turn(turn_start)
        self.turn_started_ns = turn_start
        self.turn_decision_deadline_ns = self.timing_governor.soft_deadline_ns
        self.turn_hard_deadline_ns = self.timing_governor.hard_deadline_ns
        self.turn_profile = {} if utils.DEBUG_TURN_PROFILE else None
        self._init_turn(ct)

        if self.is_assault_role and mode_assaulting.opening_escape_active(self, ct):
            utils.set_profile(self, "perception_fast_scan", 1)
            utils.set_profile(self, "perception_scan_mode", "opening_escape_skip")
            utils.set_profile(self, "perception_assault_mode", 1)
            self.stats["fast_perception_turns"] += 1
            self.logger.log(f"mode: {self.builder_mode.name}")
            if utils.DEBUG:
                self.turn_timing["perception_ns"] = 0
            m_start = time.time_ns() if utils.DEBUG else 0
            if mode_assaulting.execute_opening_escape_only(self, ct):
                if utils.DEBUG:
                    self.turn_timing["mode_ns"] = time.time_ns() - m_start
                    self.turn_timing["turn_ns"] = time.time_ns() - turn_start
                    self._log_turn_profile(ct)
                return

        p_start = time.time_ns() if utils.DEBUG else 0
        use_fast_perception = self._should_use_fast_perception(ct)
        utils.set_profile(self, "perception_fast_scan", int(use_fast_perception))
        perception.scan_around(self, ct, fast=use_fast_perception, assault_mode=bool(self.is_assault_role))
        if use_fast_perception:
            self.stats["fast_perception_turns"] += 1
        else:
            self.last_full_perception_round = ct.get_current_round()
        if utils.DEBUG:
            self.turn_timing["perception_ns"] = time.time_ns() - p_start

        self.logger.log(f"mode: {self.builder_mode.name}")
        self.logger.log("Locations - Titanium: " + str(self.titanium_locations))
        self.logger.log("Locations - Axionite: " + str(self.axionite_locations))

        if self._maybe_switch_to_hijack(ct):
            self.logger.log("Switching to opportunistic hijack mode")

        if (
            not self.is_assault_role
            and self.builder_mode != BuilderMode.TILING_BACK
            and healing.preemptive_heal_or_move(self, ct)
        ):
            if utils.DEBUG:
                self.turn_timing["mode_ns"] = 0
                self.turn_timing["turn_ns"] = time.time_ns() - turn_start
            return

        if (
            not self.is_assault_role
            and self.builder_mode == BuilderMode.EXPLORING
            and len(self.titanium_locations)
        ):
            self.builder_mode = BuilderMode.FINDING_ORE
            self.explore_target_chunk = None
            self.explore_target_pos = None

        if self._maybe_opening_unclog(ct):
            if utils.DEBUG:
                self.turn_timing["mode_ns"] = 0
                self.turn_timing["turn_ns"] = time.time_ns() - turn_start
            return

        m_start = time.time_ns() if utils.DEBUG else 0
        if self.builder_mode == BuilderMode.TILING_BACK:
            mode_tiling_back.execute(self, ct)
        elif self.builder_mode == BuilderMode.HIJACKING:
            mode_hijacking.execute(self, ct)
        elif self.builder_mode == BuilderMode.ASSAULTING:
            mode_assaulting.execute(self, ct)
        elif self.builder_mode == BuilderMode.FINDING_ORE:
            mode_finding_ore.execute(self, ct)
        elif self.builder_mode == BuilderMode.EXPLORING:
            mode_exploring.execute(self, ct)
        else:
            self.logger.print(f"unknown mode: {self.builder_mode.name}")

        if utils.DEBUG:
            self.turn_timing["mode_ns"] = time.time_ns() - m_start
            self.turn_timing["turn_ns"] = time.time_ns() - turn_start
            self._log_turn_profile(ct)

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
                    + f" abfs={self.stats['assault_bfs_replans']}"
                    + f" abfs_cache={self.stats['assault_bfs_cache_hits']}"
                )

    def _maybe_switch_to_hijack(self, ct: Controller) -> bool:
        if self.is_assault_role:
            return False
        if self.builder_mode not in {BuilderMode.FINDING_ORE, BuilderMode.EXPLORING}:
            return False

        target = mode_hijacking.find_visible_hijack_target(self, ct)
        if target is None:
            return False

        self.hijack_source_pos, self.hijack_entry_pos = target
        self.builder_mode = BuilderMode.HIJACKING
        return True

    def _maybe_opening_unclog(self, ct: Controller) -> bool:
        if self.is_assault_role:
            return False
        if self.spawn_pos is None or self.core_pos is None:
            return False
        if ct.get_current_round() > ECON_OPENING_UNCLOG_MAX_ROUND:
            return False
        if self.builder_mode not in {BuilderMode.FINDING_ORE, BuilderMode.EXPLORING}:
            return False
        if ct.get_position() != self.spawn_pos:
            return False
        if self.titanium_locations or self.axionite_locations:
            return False

        outward_dx = self.spawn_pos.x - self.core_pos.x
        outward_dy = self.spawn_pos.y - self.core_pos.y
        candidate_directions = sorted(
            utils.DIRECTIONS,
            key=lambda direction: (
                -(
                    direction.delta()[0] * outward_dx
                    + direction.delta()[1] * outward_dy
                ),
                0
                if direction in utils.CARDINAL_DIRECTIONS
                else 1,
            ),
        )

        for direction in candidate_directions:
            if ct.can_move(direction):
                ct.move(direction)
                self.logger.log(f"opening unclog via {direction.name}")
                return True
        return False

    def _log_turn_profile(self, ct: Controller) -> None:
        if (
            not utils.DEBUG_TURN_PROFILE
            or not self.turn_profile
        ):
            return

        turn_ns = self.turn_timing.get("turn_ns", 0)
        if (
            turn_ns < utils.TURN_PROFILE_THRESHOLD_NS
            and not self.turn_profile.get("assault_selected_ring_changed", 0)
        ):
            return

        utils.set_profile(self, "builder_mode", self.builder_mode.name)
        utils.set_profile(self, "is_assault_role", int(bool(self.is_assault_role)))
        utils.set_profile(self, "perception_us", self.turn_timing.get("perception_ns", 0) // 1000)
        utils.set_profile(self, "mode_us", self.turn_timing.get("mode_ns", 0) // 1000)
        profile_items = [
            f"round={ct.get_current_round()}",
            f"turn_us={turn_ns // 1000}",
            f"pos=({ct.get_position().x},{ct.get_position().y})",
        ]
        for key in sorted(self.turn_profile):
            profile_items.append(f"{key}={self.turn_profile[key]}")
        self.logger.print("turn_profile " + " ".join(profile_items))
