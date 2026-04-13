from cambc import Controller, EntityType
from states import BuilderMode, TargetKind
import logger
import mode_assaulting
import perception
import mode_exploring
import mode_finding_ore
import mode_hijacking
import mode_rush
import mode_tiling_back
import healing
import defense
import timing
import utils
import time

SOFT_DECISION_DEADLINE_NANOSECONDS = timing.SOFT_DECISION_BUDGET_NS
# Assault builders now stay on the cheap local scan by default and only pay
# for a full refresh on a periodic heartbeat or after they leave the spawn
# bootstrap shell.
ASSAULT_FULL_PERCEPTION_INTERVAL = 6
ECON_SEARCH_FULL_PERCEPTION_INTERVAL = 4
ECON_STEADY_FULL_PERCEPTION_INTERVAL = 8
ECON_TILING_FAST_PERCEPTION_INTERVAL = 10
ECON_OPENING_UNCLOG_MAX_ROUND = 18
ECON_STALL_RESET_INTERVAL = 150
RUSH_ASSIGNMENT_MIN_ROUND = 80
RUSH_ASSIGNMENT_SLOTS = {0, 1, 2, 3}
SYMMETRY_MODES = ("ROT180", "MIRROR_X", "MIRROR_Y")

# Generic small-loop killer. Tracks the last SMALL_LOOP_HISTORY positions
# of this builder; if the unique-position count drops below
# SMALL_LOOP_UNIQUE_THRESHOLD for SMALL_LOOP_BREAK_THRESHOLD consecutive
# turns we force a recovery (clear blacklist + ore target + switch to
# EXPLORING) so the bot stops thrashing in a 1-3 tile cycle for hundreds
# of turns. Replay analysis showed builders with small_loop_streak
# approaching 2000 turns — completely wasted CPU and economy.
SMALL_LOOP_HISTORY = 8
SMALL_LOOP_UNIQUE_THRESHOLD = 2
SMALL_LOOP_BREAK_THRESHOLD = 12


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
        self.is_rush_builder = False

        self.grid = {}
        self.grid_env_known_count = 0

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
        # Axionite foundry placement plan produced by
        # `axionite_planner.plan_axionite_foundry_placement` on ax
        # harvester commit. When set, tiling-back executes the
        # foundry + refined-ax conveyor builds along the plan. Cleared
        # once the plan is executed or abandoned.
        self.pending_axionite_plan = None
        self.pathfinding_state = {
            "known_obstacles": set(),
            "path": [],
            "temporary_obstacles": {},
            "current_target": None,
            "last_obstacle_signature": None,
            "last_replan_signature": None,
            "last_replan_round": -1,
            "planner_state": None,
        }

        self.explored_tiles = set()
        self.explored_chunk_last_seen = {}
        self.all_map_chunks = None
        self.explore_target_chunk = None
        self.explore_target_pos = None
        self.claimed_explore_chunks = set()
        self.claimed_assault_anchor_keys = set()
        self.claimed_pipeline_positions = set()
        self.shared_ore_positions = set()
        self.shared_connected_conveyor_positions = set()
        self.shared_connected_harvester_positions = set()
        self.shared_pipeline_claim_positions = set()
        self.last_pipeline_claim_round = -9999

        self.last_harvester_pos = None
        self.tiled_back_positions = set()
        self.pending_build = None
        self.nearest_conveyor_pos = None
        self.nearest_conveyor_dist_manhatten = float("inf")
        self.return_target_pos = None
        self.return_target_dist_manhatten = float("inf")
        self.return_target_kind = TargetKind.CORE
        self.core_return_target_pos = None
        self.core_lane_slot_pos = None
        self.core_lane_core_tile_pos = None
        self.core_lane_exit_built = False
        self.tiling_force_core_return = False
        self.tiling_prefer_core_return = False
        self.tiling_core_approach_full = False
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
        self.rush_target_core_pos = None
        self.rush_turret_pos = None
        self.rush_build_stance = None
        self.rush_turret_type = None
        self.rush_turret_direction = None
        self.rush_symmetry_candidates = None
        self.rush_failed_candidates = set()
        self.rush_turret_built = False

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
            "anytime_exact_paths": 0,
            "anytime_partial_paths": 0,
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
        self.last_defense_build_round = -9999
        # Generic small-loop killer state — see SMALL_LOOP_* constants.
        self.small_loop_position_history: list[tuple[int, int]] = []
        self.small_loop_streak = 0
        self.last_small_loop_recovery_round = -9999
        self.healing_this_turn = False

    def _init_turn(self, ct: Controller):
        if self.logger is None:
            self.logger = logger.Logger(ct)
        if self.spawn_pos is None:
            self.spawn_pos = ct.get_position()

        if self.core_pos is None:
            my_team = ct.get_team()
            cores = [
                entity_id
                for entity_id in ct.get_nearby_entities()
                if ct.get_entity_type(entity_id) == EntityType.CORE
                and ct.get_team(entity_id) == my_team
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
                if (
                    self.spawn_slot in RUSH_ASSIGNMENT_SLOTS
                    and ct.get_current_round() >= RUSH_ASSIGNMENT_MIN_ROUND
                ):
                    self.is_rush_builder = True
                    self.builder_mode = BuilderMode.RUSH
                else:
                    self.builder_mode = BuilderMode.ASSAULTING
                self.assault_last_progress_round = ct.get_current_round()

    def stop_rushing(self, fallback: BuilderMode = BuilderMode.ASSAULTING):
        if not self.is_rush_builder:
            return
        self.is_rush_builder = False
        self.builder_mode = fallback
        self.rush_target_core_pos = None
        self.rush_turret_pos = None
        self.rush_build_stance = None
        self.rush_turret_type = None
        self.rush_turret_direction = None
        self.rush_symmetry_candidates = None
        self.rush_failed_candidates = set()
        self.rush_turret_built = False

    def _should_use_fast_perception(self, ct: Controller) -> bool:
        current_round = ct.get_current_round()
        if self.last_full_perception_round < 0:
            return False

        if not self.is_assault_role:
            if self.builder_mode in {BuilderMode.FINDING_ORE, BuilderMode.EXPLORING}:
                interval = (
                    ECON_STEADY_FULL_PERCEPTION_INTERVAL
                    if self.titanium_locations
                    else ECON_SEARCH_FULL_PERCEPTION_INTERVAL
                )
                return current_round - self.last_full_perception_round < interval

            return (
                self.builder_mode == BuilderMode.TILING_BACK
                and current_round - self.last_full_perception_round
                < ECON_TILING_FAST_PERCEPTION_INTERVAL
            )

        if mode_assaulting.opening_escape_active(self, ct):
            return True

        return (
            current_round - self.last_full_perception_round
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
            if utils.DEBUG:
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

        # Note: no post-perception no-op bail. Even when the turn is tight
        # on time we still enter mode execution — A*'s internal time guard
        # (A_STAR_TIME_GUARD_NANOSECONDS + get_available_astar_time_budget)
        # clamps the planner's budget and falls through to the resumable
        # planner_state / cached path / greedy fallback, so the builder
        # always tries to emit SOME action rather than producing a true
        # no-op turn.

        if utils.DEBUG:
            self.logger.log(f"mode: {self.builder_mode.name}")
            self.logger.log("Locations - Titanium: " + str(self.titanium_locations))
            self.logger.log("Locations - Axionite: " + str(self.axionite_locations))

        if defense.core_port_guard_if_needed(self, ct):
            if utils.DEBUG:
                self.turn_timing["mode_ns"] = 0
                self.turn_timing["turn_ns"] = time.time_ns() - turn_start
            return

        if defense.defend_core_if_needed(self, ct):
            if utils.DEBUG:
                self.turn_timing["mode_ns"] = 0
                self.turn_timing["turn_ns"] = time.time_ns() - turn_start
            return

        if (
            not self.is_assault_role
            and self.builder_mode != BuilderMode.TILING_BACK
            and healing.preemptive_heal_or_move(self, ct)
        ):
            if utils.DEBUG:
                self.turn_timing["mode_ns"] = 0
                self.turn_timing["turn_ns"] = time.time_ns() - turn_start
            return

        if self.builder_mode != BuilderMode.HIJACKING:
            if defense.defend_lane_if_needed(self, ct):
                if utils.DEBUG:
                    self.turn_timing["mode_ns"] = 0
                    self.turn_timing["turn_ns"] = time.time_ns() - turn_start
                return

        if self._maybe_switch_to_hijack(ct):
            if utils.DEBUG:
                self.logger.log("Switching to opportunistic hijack mode")

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

        if not self.is_assault_role:
            self._maybe_reset_economy_stall(ct)

        m_start = time.time_ns() if utils.DEBUG else 0
        self.healing_this_turn = False
        if self.builder_mode == BuilderMode.TILING_BACK:
            mode_tiling_back.execute(self, ct)
        elif self.builder_mode == BuilderMode.HIJACKING:
            mode_hijacking.execute(self, ct)
        elif self.builder_mode == BuilderMode.RUSH:
            mode_rush.execute(self, ct)
        elif self.builder_mode == BuilderMode.ASSAULTING:
            mode_assaulting.execute(self, ct)
        elif self.builder_mode == BuilderMode.FINDING_ORE:
            mode_finding_ore.execute(self, ct)
        elif self.builder_mode == BuilderMode.EXPLORING:
            mode_exploring.execute(self, ct)
        else:
            self.logger.print(f"unknown mode: {self.builder_mode.name}")

        # Generic small-loop killer. Runs after mode execution and only
        # in non-healing turns. Prevents the "stuck in 1-3 tile cycle for
        # 1500+ turns" failure mode the analyzer reports across batches.
        self._note_small_loop_progress(ct)

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
                if utils.DEBUG:
                    self.logger.log(f"opening unclog via {direction.name}")
                return True
        return False

    def _note_small_loop_progress(self, ct: Controller) -> None:
        """Track post-mode position history and force a state recovery
        when the builder has been cycling in a tight set of tiles.

        Tracks history across ALL modes (so a builder bouncing between
        TILING_BACK and FINDING_ORE on the same stuck location is still
        detected) and only suppresses recovery on heal turns. Recovery is
        intentionally lightweight: it tears down the cached pathfinding
        / planner state, clears the ore blacklist + ore target, and
        releases pending builds. We do NOT force a mode change — the
        next turn's normal mode planner picks up with fresh state and
        will either find a different ore target or naturally transition
        between modes."""
        if self.healing_this_turn:
            return
        try:
            current_pos = ct.get_position()
        except Exception:
            return
        pos_key = (current_pos.x, current_pos.y)
        history = self.small_loop_position_history
        history.append(pos_key)
        if len(history) > SMALL_LOOP_HISTORY:
            history.pop(0)
        if len(history) < SMALL_LOOP_HISTORY:
            return
        unique = set(history)
        if len(unique) <= SMALL_LOOP_UNIQUE_THRESHOLD:
            self.small_loop_streak += 1
        else:
            self.small_loop_streak = 0
            return
        if self.small_loop_streak < SMALL_LOOP_BREAK_THRESHOLD:
            return
        round_now = ct.get_current_round()
        if round_now - self.last_small_loop_recovery_round < SMALL_LOOP_BREAK_THRESHOLD:
            return
        # Recovery: tear down stuck state. Do not force a mode change —
        # let the next turn's mode planner re-enter with fresh state.
        self.last_small_loop_recovery_round = round_now
        self.small_loop_streak = 0
        history.clear()
        self.ore_target_blacklist.clear()
        self.ore_target_state = {"ore": None, "access": None, "stuck_turns": 0}
        self.pathfinding_state["path"] = []
        self.pathfinding_state["planner_state"] = None
        self.pathfinding_state["last_replan_signature"] = None
        self.pathfinding_state["temporary_obstacles"] = {}
        self.return_target_pos = None
        self.return_target_dist_manhatten = float("inf")
        self.pending_build = None
        self.pending_bridge_plan = None
        self.bridge_transit_path = None
        # Bounce out of explore-target lock so the next exploring turn
        # picks a fresh chunk if it stays in EXPLORING.
        self.explore_target_chunk = None
        self.explore_target_pos = None
        if utils.DEBUG:
            self.logger.log(
                f"small loop killer: state cleanup at {pos_key} after "
                f"{SMALL_LOOP_BREAK_THRESHOLD}+ stuck turns"
            )

    def _maybe_reset_economy_stall(self, ct: Controller) -> None:
        """If the builder hasn't placed a harvester in ECON_STALL_RESET_INTERVAL
        turns, clear ore blacklists and tiling-back failure counts to give it a
        fresh start.  This prevents permanent deadlocks where all nearby ore is
        permanently blacklisted."""
        round_now = ct.get_current_round()
        last_success = getattr(self, "last_harvester_place_round", 0)
        last_reset = getattr(self, "last_econ_stall_reset_round", 0)
        if round_now - max(last_success, last_reset) < ECON_STALL_RESET_INTERVAL:
            return

        self.last_econ_stall_reset_round = round_now
        cleared_targets = len(self.ore_target_blacklist)
        cleared_failures = len(getattr(self, "tiling_back_fail_counts", {}))
        self.ore_target_blacklist.clear()
        if hasattr(self, "tiling_back_fail_counts"):
            self.tiling_back_fail_counts.clear()
        if hasattr(self, "unreachable_chunks"):
            self.unreachable_chunks.clear()
        if utils.DEBUG and (cleared_targets or cleared_failures):
            self.logger.log(
                f"economy stall reset: cleared {cleared_targets} blacklisted ore "
                f"and {cleared_failures} tiling failure counts"
            )

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
