"""Rolling-horizon belief FSM focused on titanium throughput and local repair."""

from __future__ import annotations

import atexit
from collections import Counter, deque
from dataclasses import dataclass, field
from enum import Enum, auto
import json
import math
import os
from pathlib import Path
from time import perf_counter_ns

import cambc
from cambc import Controller, Direction, EntityType, Environment, GameConstants, Position, Team

from bots.policy_fsm_v3.runtime.decision import (
    BuildDecision,
    BuildKind,
    ConvertDecision,
    FireDecision,
    MarkerDecision,
    MoveDecision,
    RotateDecision,
    TurnPlan,
)
from bots.policy_fsm_v3.runtime.markers import MarkerKind, decode_marker, is_recent_marker, marker_age
from bots.policy_fsm_v3.runtime.markers import (
    ClaimLaneStatus,
    decode_titanium_lane_status,
    encode_titanium_lane_status,
)
from bots.policy_fsm_v3.runtime.nav import (
    CARDINAL_DIRECTIONS,
    choose_bug_escape_step,
    find_path_to_best_frontier,
    find_path_to_visible_goal,
    is_traversable_for_planning,
    manhattan_distance,
    ore_adjacent_goals,
    unknown_neighbor_count,
)
from bots.policy_fsm_v3.runtime.sense import EntityInfo, TileInfo, TurnContext

from .common import BaseTrailSolution


class BuilderStateV3(Enum):
    FRONTIER_PUSH = auto()
    CLAIM_TITANIUM = auto()
    ROUTE_HOME_SAFE = auto()
    PATROL = auto()
    REACTIVE_DEFEND = auto()


class PatrolMode(Enum):
    DEEP_FRONTIER = auto()
    MID_SWEEP = auto()
    HOME_GUARD = auto()


class SearchKind(Enum):
    ORE = auto()
    FRONTIER = auto()
    ESCAPE = auto()


class RouteHealth(Enum):
    HEALTHY_LOCAL = auto()
    REPAIRABLE_FAULT = auto()
    CONGESTED = auto()
    UNKNOWN = auto()
    UNSALVAGEABLE_LOCAL = auto()


@dataclass(slots=True)
class PendingHarvester:
    target: Position
    retries: int = 0


@dataclass(slots=True)
class BlacklistEntry:
    expires_round: int


@dataclass(slots=True)
class BeliefTile:
    environment: Environment | None
    building_type: EntityType | None
    building_team: Team | None
    direction: Direction | None
    last_seen_round: int
    last_occupied_round: int
    bridge_target: Position | None = None


@dataclass(slots=True)
class OreMemory:
    position: Position
    environment: Environment
    last_seen_round: int
    has_friendly_harvester: bool = False
    last_harvester_round: int = -1
    last_healthy_round: int = -1


@dataclass(slots=True)
class OreCluster:
    centroid: Position
    members: list[Position]
    last_seen_round: int


@dataclass(slots=True)
class SearchTicket:
    kind: SearchKind
    goals: set[Position]
    waypoint: Position
    queue: deque[Position]
    parents: dict[Position, Position | None]
    visited: set[Position]
    origin: Position
    expanded_total: int = 0
    exhausted: bool = False


@dataclass(slots=True)
class MicroPath:
    kind: SearchKind
    waypoint: Position
    steps: list[Position]
    created_round: int


@dataclass(slots=True)
class LaneHealthReport:
    ore_position: Position
    status: RouteHealth
    anomaly_tiles: list[Position] = field(default_factory=list)
    repair_directions: dict[Position, Direction] = field(default_factory=dict)
    congested_tiles: list[Position] = field(default_factory=list)
    segment_tiles: list[Position] = field(default_factory=list)


@dataclass(slots=True)
class ActionMask:
    allowed_moves: dict[Direction, Position] = field(default_factory=dict)
    blocked_moves: dict[Direction, str] = field(default_factory=dict)
    blocked_build_positions: dict[Position, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CapabilityFlags:
    supports_convert: bool
    supports_rotate: bool
    supports_get_attackable_tiles: bool


@dataclass(frozen=True, slots=True)
class PolicyFSMV3Config:
    claim_horizon: int = 18
    claim_refresh_turns: int = 8
    planner_expand_default_budget: int = 8
    planner_expand_mid_budget: int = 14
    planner_expand_budget: int = 24
    planner_cpu_stop_us: int = 1300
    planner_guard_band_us: int = 180
    planner_deadline_check_interval: int = 1
    planner_search_min_remaining_us: int = 520
    planner_search_budget_cap_us: int = 240
    planner_non_ore_search_budget_cap_us: int = 140
    planner_search_entry_margin_us: int = 80
    slow_path_min_remaining_us: int = 180
    micro_path_len: int = 4
    ore_path_query_limit: int = 2
    ore_candidate_eval_limit: int = 2
    ore_prefilter_limit: int = 12
    ore_scoring_min_remaining_us: int = 420
    ore_path_max_nodes: int = 160
    visible_ore_hard_limit: int = 18
    ore_memory_ttl: int = 240
    artery_memory_ttl: int = 40
    occupancy_memory_ttl: int = 4
    frontier_memory_ttl: int = 80
    frontier_track_tile_cap: int = 56
    ore_cluster_rebuild_interval: int = 8
    symmetry_update_interval: int = 8
    memory_expire_interval: int = 8
    fast_path_belief_refresh_interval: int = 20
    local_harvester_belief_refresh_interval: int = 10
    repair_marker_belief_refresh_interval: int = 6
    lane_viability_check_interval: int = 6
    lane_blacklist_ttl: int = 36
    splice_blacklist_ttl: int = 24
    loop_blacklist_ttl: int = 10
    small_loop_risk_window: int = 16
    dispersion_neighbor_radius: int = 4
    dispersion_push_distance: int = 5
    dispersion_congestion_radius: int = 2
    dispersion_congestion_threshold: int = 2
    congestion_blacklist_ttl: int = 12
    route_stall_turns: int = 4
    route_wait_turns: int = 2
    path_stall_turns: int = 8
    unresolved_lane_patience_turns: int = 20
    defend_titanium_threshold: int = 20
    defend_radius: int = 2
    search_goal_horizon: int = 14
    route_segment_limit: int = 16
    route_memory_ttl: int = 10
    flow_window: int = 20
    flow_inbound_min_rounds: int = 10
    flow_avg_inflow_threshold: int = 12
    min_healthy_harvesters_for_axionite: int = 2
    axionite_idle_reserve: int = 10
    axionite_threat_reserve: int = 20
    route_health_local_radius: int = 7
    route_health_scan_interval: int = 14
    route_health_max_reports: int = 3
    route_health_scan_min_remaining_us: int = 340
    throughput_congestion_observations: int = 1
    throughput_scan_freshness_rounds: int = 48
    delivery_confirm_window: int = 8
    delivery_confirm_net_inflow: int = 30
    delivery_confirm_inbound_rounds: int = 4
    early_exploration_round: int = 200
    early_exploration_ore_target: int = 3
    core_spawn_pressure_round: int = 45
    core_spawn_pressure_visible_ore_target: int = 2
    pre_delivery_spawn_cap_default: int = 6
    pre_delivery_spawn_cap_discovery_early: int = 8
    pre_delivery_spawn_cap_discovery_mid: int = 10
    pre_delivery_spawn_cap_discovery_late: int = 12
    pre_delivery_soft_lane_reserve_conveyors: int = 2
    frontier_cache_refresh_rounds_discovery: int = 2
    full_belief_resync_period: int = 180
    full_belief_resync_min_remaining_us: int = 700
    belief_refresh_min_remaining_us: int = 340
    frontier_belief_min_remaining_us: int = 640
    symmetry_update_min_remaining_us: int = 760


ACTIVE_CONFIG = PolicyFSMV3Config()


OPPOSITE_DIRECTION = {
    Direction.NORTH: Direction.SOUTH,
    Direction.SOUTH: Direction.NORTH,
    Direction.EAST: Direction.WEST,
    Direction.WEST: Direction.EAST,
}

DIAGONAL_DIRECTIONS = (
    Direction.NORTHEAST,
    Direction.SOUTHEAST,
    Direction.SOUTHWEST,
    Direction.NORTHWEST,
)

MANHATTAN_RADIUS2_OFFSETS = tuple(
    (dx, dy)
    for dx in range(-2, 3)
    for dy in range(-2, 3)
    if (dx != 0 or dy != 0) and abs(dx) + abs(dy) <= 2
)


def _detect_capabilities() -> CapabilityFlags:
    # The imported Controller class is an empty placeholder outside engine runtime,
    # so class-level hasattr() probes are unreliable in local tests. Use the
    # installed SDK version/constants as the capability baseline instead.
    version = getattr(cambc, "__version__", "")
    version_tuple: tuple[int, ...] = tuple(
        int(part)
        for part in version.split(".")
        if part.isdigit()
    )
    has_sdk_153 = version_tuple >= (1, 5, 3)
    return CapabilityFlags(
        supports_convert=has_sdk_153,
        supports_rotate=has_sdk_153 and hasattr(GameConstants, "GUNNER_ROTATE_COST"),
        supports_get_attackable_tiles=has_sdk_153 and hasattr(GameConstants, "GUNNER_AXIONITE_DAMAGE"),
    )


class PolicyFSMV3Solution(BaseTrailSolution):
    """FSM with persistent local belief, bounded planning, and local fault repair."""

    ROUTE_BUILDABLE_TYPES = {None, EntityType.ROAD, EntityType.MARKER}
    PROTECTED_LOGISTICS = {
        EntityType.CORE,
        EntityType.CONVEYOR,
        EntityType.SPLITTER,
        EntityType.BRIDGE,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.HARVESTER,
        EntityType.FOUNDRY,
    }
    TURRET_TYPES = {
        EntityType.GUNNER,
        EntityType.SENTINEL,
        EntityType.BREACH,
        EntityType.LAUNCHER,
    }

    SYMMETRY_MODES = ("ROT180", "MIRROR_X", "MIRROR_Y")

    def __init__(self, config: PolicyFSMV3Config = ACTIVE_CONFIG):
        super().__init__()
        self.config = config
        self.capabilities = _detect_capabilities()
        self.builder_state = BuilderStateV3.FRONTIER_PUSH
        self.current_lane_target: Position | None = None
        self.current_lane_goal: Position | None = None
        self.pending_harvester: PendingHarvester | None = None
        self.observed_first_delivery_round: int | None = None
        self.last_seen_titanium: int | None = None
        self.last_observed_round: int = -1
        self.last_core_spend_round: int = -1
        self.last_core_spend: int = 0

        self.recent_positions: list[Position] = []
        self.path_history: list[Position] = []
        self.route_history: list[Position] = []
        self.route_cursor: int | None = None

        self.failed_lanes: dict[tuple[int, int], BlacklistEntry] = {}
        self.blocked_splices: dict[tuple[int, int], BlacklistEntry] = {}
        self.loop_blacklist: dict[tuple[int, int], BlacklistEntry] = {}
        self.congestion_blacklist: dict[tuple[int, int], BlacklistEntry] = {}

        self.route_last_position: Position | None = None
        self.route_stall_counter = 0
        self.route_wait_target: Position | None = None
        self.route_wait_counter = 0
        self.route_resume_target: Position | None = None
        self.route_resume_failures = 0
        self.route_pending_bridge: tuple[Position, Position] | None = None

        self.goal_stall_counter = 0
        self.last_goal_distance: int | None = None
        self.current_lane_started_round = -1
        self.patrol_cycle = 0
        self.last_patrol_round = -1

        self.last_claim_target: Position | None = None
        self.last_claim_round = -1

        self.belief_tiles: dict[Position, BeliefTile] = {}
        self.ore_memory: dict[Position, OreMemory] = {}
        self.ore_clusters: list[OreCluster] = []
        self.healthy_artery_tiles: dict[tuple[int, int], int] = {}
        self.frontier_candidates: dict[tuple[int, int], int] = {}
        self.frontier_unknown_scores: dict[tuple[int, int], int] = {}
        self.visit_counts: Counter[tuple[int, int]] = Counter()

        self.symmetry_candidates: set[str] = set(self.SYMMETRY_MODES)
        self.symmetry_mode: str | None = None
        self.predicted_enemy_anchor: Position | None = None

        self.active_search_ticket: SearchTicket | None = None
        self.micro_path: MicroPath | None = None
        self.last_planner_expansions: int = 0
        self.frontier_waypoint_cache: Position | None = None
        self.frontier_waypoint_cache_round: int = -1

        self.congestion_streaks: dict[tuple[int, int], tuple[int, int]] = {}
        self.lane_congestion_observations: dict[tuple[int, int], tuple[int, int]] = {}
        self.turn_cache_round = -1
        self.turn_ore_path_cache: dict[tuple[int, int], int | None] = {}
        self.turn_ore_goals_cache: dict[tuple[int, int], set[Position]] = {}
        self.turn_lane_claim_block_cache: dict[tuple[int, int], bool] = {}
        self.turn_logistics_positions_cache: set[Position] | None = None
        self.turn_friendly_builder_positions_cache: list[Position] | None = None
        self.turn_ore_path_queries = 0
        self.last_ore_cluster_rebuild_round = -9999
        self.last_symmetry_update_round = -9999
        self.last_memory_expire_round = -9999
        self.last_belief_update_round = -9999
        self.last_route_health_scan_round = -9999
        self.last_lane_viability_round = -9999
        self.last_full_belief_resync_round = -9999
        self.ore_memory_dirty = True
        self.symmetry_dirty = True
        self.full_belief_resync_period: int = self.config.full_belief_resync_period

        self.net_titanium_inflow_window: deque[int] = deque(maxlen=self.config.flow_window)
        self.inbound_logistics_window: deque[bool] = deque(maxlen=self.config.flow_window)
        self.profile_enabled = os.environ.get("FSM_V3_PROFILE") == "1"
        self.profile_output_dir = Path(os.environ.get("FSM_V3_PROFILE_DIR", "/tmp"))
        self.profile_totals_ns: Counter[str] = Counter()
        self.profile_counts: Counter[str] = Counter()
        self.profile_max_ns: Counter[str] = Counter()
        self.profile_over_1ms: Counter[str] = Counter()
        self.profile_over_2ms: Counter[str] = Counter()
        self.profile_entity_type: str | None = None
        self.profile_entity_id: int | None = None
        self.builder_turn_start_ns: int = 0
        if self.profile_enabled:
            atexit.register(self._flush_profile)

    def decide(self, context: TurnContext) -> TurnPlan:
        if self.profile_enabled:
            self.profile_entity_type = context.entity_type.value
            self.profile_entity_id = context.entity_id
            observe_start = perf_counter_ns()
            self._observe_team_titanium(context)
            self._profile_record("observe_team_titanium", perf_counter_ns() - observe_start)
        else:
            self._observe_team_titanium(context)
        if context.entity_type == EntityType.CORE:
            return self._decide_core(context)
        if context.entity_type == EntityType.BUILDER_BOT:
            builder_start = perf_counter_ns()
            self.builder_turn_start_ns = builder_start
            if self.profile_enabled:
                plan = self._decide_builder(context)
                self._profile_record("decide_builder_total", perf_counter_ns() - builder_start)
                self.builder_turn_start_ns = 0
                return plan
            plan = self._decide_builder(context)
            self.builder_turn_start_ns = 0
            return plan
        if context.entity_type in self.TURRET_TYPES:
            return self._decide_turret(context)
        return TurnPlan(note="policy_fsm_v3 idle")

    def _profile_record(self, key: str, elapsed_ns: int) -> None:
        if not self.profile_enabled:
            return
        self.profile_totals_ns[key] += elapsed_ns
        self.profile_counts[key] += 1
        if elapsed_ns > self.profile_max_ns[key]:
            self.profile_max_ns[key] = elapsed_ns
        if elapsed_ns >= 1_000_000:
            self.profile_over_1ms[key] += 1
        if elapsed_ns >= 2_000_000:
            self.profile_over_2ms[key] += 1

    def _flush_profile(self) -> None:
        if not self.profile_enabled or not self.profile_totals_ns:
            return
        self.profile_output_dir.mkdir(parents=True, exist_ok=True)
        entity_type = (self.profile_entity_type or "unknown").lower()
        entity_id = self.profile_entity_id if self.profile_entity_id is not None else "unknown"
        output_path = self.profile_output_dir / f"policy_fsm_v3_profile_{os.getpid()}_{entity_type}_{entity_id}.json"
        averages_ns = {
            key: (self.profile_totals_ns[key] / self.profile_counts[key])
            for key in self.profile_totals_ns
            if self.profile_counts[key] > 0
        }
        payload = {
            "pid": os.getpid(),
            "entity_id": self.profile_entity_id,
            "entity_type": self.profile_entity_type,
            "totals_ns": dict(self.profile_totals_ns),
            "counts": dict(self.profile_counts),
            "averages_ns": averages_ns,
            "max_ns": dict(self.profile_max_ns),
            "over_1ms": dict(self.profile_over_1ms),
            "over_2ms": dict(self.profile_over_2ms),
        }
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _in_bounds(self, context: TurnContext, position: Position) -> bool:
        return 0 <= position.x < context.map_width and 0 <= position.y < context.map_height

    def _tile_key(self, position: Position) -> tuple[int, int]:
        return (position.x, position.y)

    def _observe_team_titanium(self, context: TurnContext) -> None:
        if self.last_observed_round == context.round_num:
            return
        previous = self.last_seen_titanium
        delta = 0 if previous is None else context.titanium - previous
        spend = self.last_core_spend if self.last_core_spend_round == context.round_num - 1 else 0
        net_inflow = delta + spend
        self.net_titanium_inflow_window.append(net_inflow)
        observe_inbound = (
            context.entity_type == EntityType.CORE
            or (
                self.anchor_position is not None
                and manhattan_distance(context.position, self.anchor_position) <= 4
            )
        )
        inbound = (
            self._visible_inbound_logistics_evidence(context)
            if observe_inbound
            else (self.inbound_logistics_window[-1] if self.inbound_logistics_window else False)
        )
        self.inbound_logistics_window.append(inbound)
        self.last_seen_titanium = context.titanium
        self.last_observed_round = context.round_num
        if (
            previous is not None
            and context.titanium > previous
            and inbound
            and self.observed_first_delivery_round is None
        ):
            window = self.config.delivery_confirm_window
            if (
                len(self.net_titanium_inflow_window) >= window
                and len(self.inbound_logistics_window) >= window
            ):
                recent_inflow = list(self.net_titanium_inflow_window)[-window:]
                recent_inbound = list(self.inbound_logistics_window)[-window:]
                positive_inflow = sum(max(0, value) for value in recent_inflow)
                inbound_rounds = sum(1 for evidence in recent_inbound if evidence)
                if (
                    inbound_rounds >= self.config.delivery_confirm_inbound_rounds
                    and positive_inflow >= self.config.delivery_confirm_net_inflow
                ):
                    self.observed_first_delivery_round = context.round_num

    def _decision_elapsed_us(self) -> int:
        if self.builder_turn_start_ns <= 0:
            return 0
        return max(0, (perf_counter_ns() - self.builder_turn_start_ns) // 1000)

    def _planner_remaining_us(self, context: TurnContext) -> int:
        baseline_elapsed = max(context.cpu_time_us, 0)
        measured_elapsed = self._decision_elapsed_us()
        consumed = max(baseline_elapsed, measured_elapsed)
        return max(0, self.config.planner_cpu_stop_us - consumed - self.config.planner_guard_band_us)

    def _reset_turn_caches(self, context: TurnContext) -> None:
        if self.turn_cache_round == context.round_num:
            return
        self.turn_cache_round = context.round_num
        self.turn_ore_path_cache.clear()
        self.turn_ore_goals_cache.clear()
        self.turn_lane_claim_block_cache.clear()
        self.turn_logistics_positions_cache = None
        self.turn_friendly_builder_positions_cache = None
        self.turn_ore_path_queries = 0

    def _visible_inbound_logistics_evidence(self, context: TurnContext) -> bool:
        if self.anchor_position is None:
            return False
        for tile in context.tiles.values():
            if tile.building_team != context.team or tile.building_type not in (
                EntityType.CONVEYOR,
                EntityType.BRIDGE,
            ):
                continue
            if manhattan_distance(tile.position, self.anchor_position) > 8:
                continue
            entity = context.entities.get(tile.building_id) if tile.building_id is not None else None
            if entity is None:
                continue
            output: Position | None = None
            if tile.building_type == EntityType.CONVEYOR:
                if entity.direction is None:
                    continue
                output = tile.position.add(entity.direction)
            elif tile.building_type == EntityType.BRIDGE:
                output = entity.bridge_target
            if output is None:
                continue
            if output == self.anchor_position:
                return True
            if manhattan_distance(output, self.anchor_position) < manhattan_distance(tile.position, self.anchor_position):
                return True
        return False

    def _remember_recent_position(self, position: Position) -> None:
        self.recent_positions.append(position)
        if len(self.recent_positions) > 32:
            self.recent_positions = self.recent_positions[-32:]

    def _remember_path_history(self, position: Position) -> None:
        if self.path_history and self.path_history[-1] == position:
            return
        self.path_history.append(position)
        if len(self.path_history) > 128:
            self.path_history = self.path_history[-128:]

    def _reset_goal_progress(self) -> None:
        self.goal_stall_counter = 0
        self.last_goal_distance = None

    def _mark_lane_commit(self, context: TurnContext, ore_position: Position) -> None:
        if self.current_lane_target != ore_position:
            self.current_lane_started_round = context.round_num

    def _abandon_stalled_goal(self, context: TurnContext) -> bool:
        if self.current_lane_goal is None:
            self._reset_goal_progress()
            return False
        distance = manhattan_distance(context.position, self.current_lane_goal)
        if self.last_goal_distance is None or distance < self.last_goal_distance:
            self.goal_stall_counter = 0
        else:
            self.goal_stall_counter += 1
        self.last_goal_distance = distance
        if self.goal_stall_counter < self.config.path_stall_turns:
            return False
        if self.current_lane_target is not None:
            if self._has_fresher_foreign_lane_owner(context, self.current_lane_target):
                self._mark_lane_failed(self.current_lane_target, context)
            else:
                goals = self._ore_adjacent_positions(context, self.current_lane_target)
                has_viable_goal = bool(goals) and any(
                    not self._goal_is_hard_blocked(context, goal)
                    for goal in goals
                )
                target_memory = self.ore_memory.get(self.current_lane_target)
                has_recent_target_evidence = (
                    self.current_lane_target in context.tiles
                    or (
                        target_memory is not None
                        and target_memory.last_seen_round >= context.round_num - self.config.ore_memory_ttl
                    )
                )
                unresolved_lane = (
                    self.current_lane_started_round >= 0
                    and context.round_num - self.current_lane_started_round <= self.config.unresolved_lane_patience_turns
                )
                # Some maps require temporary detours that increase Manhattan
                # distance before a lane becomes reachable. Avoid prematurely
                # abandoning viable lanes unless we detect local looping or
                # prolonged stall beyond a hard cap.
                if has_recent_target_evidence and has_viable_goal and not self._small_loop_risk(window=24):
                    if unresolved_lane or self.goal_stall_counter < self.config.path_stall_turns * 4:
                        return False
                self._mark_lane_failed(self.current_lane_target, context)
        self.current_lane_target = None
        self.current_lane_started_round = -1
        self.current_lane_goal = None
        self.pending_harvester = None
        self.active_search_ticket = None
        self.micro_path = None
        self._reset_goal_progress()
        return True

    def _recent_visit_count(self, position: Position) -> int:
        key = self._tile_key(position)
        return int(self.visit_counts[key])

    def _is_ping_pong(self) -> bool:
        if len(self.recent_positions) < 4:
            return False
        a, b, c, d = self.recent_positions[-4:]
        return a == c and b == d and a != b

    def _small_loop_active(self) -> bool:
        if len(self.recent_positions) < 24:
            return False
        window = self.recent_positions[-24:]
        return len(set(window)) <= 3

    def _small_loop_risk(self, window: int | None = None) -> bool:
        risk_window = self.config.small_loop_risk_window if window is None else window
        if len(self.recent_positions) < risk_window:
            return False
        return len(set(self.recent_positions[-risk_window:])) <= 3

    def _expire_blacklists(self, context: TurnContext) -> None:
        self.failed_lanes = {
            key: value for key, value in self.failed_lanes.items() if value.expires_round > context.round_num
        }
        self.blocked_splices = {
            key: value for key, value in self.blocked_splices.items() if value.expires_round > context.round_num
        }
        self.loop_blacklist = {
            key: value for key, value in self.loop_blacklist.items() if value.expires_round > context.round_num
        }
        self.congestion_blacklist = {
            key: value for key, value in self.congestion_blacklist.items() if value.expires_round > context.round_num
        }

    def _expire_memory(self, context: TurnContext) -> None:
        if context.round_num - self.last_memory_expire_round < self.config.memory_expire_interval:
            return
        self.last_memory_expire_round = context.round_num
        ore_cutoff = context.round_num - self.config.ore_memory_ttl
        previous_ore_count = len(self.ore_memory)
        self.ore_memory = {
            position: memory
            for position, memory in self.ore_memory.items()
            if memory.last_seen_round >= ore_cutoff
        }
        if len(self.ore_memory) != previous_ore_count:
            self.ore_memory_dirty = True
        self.frontier_candidates = {
            key: seen_round
            for key, seen_round in self.frontier_candidates.items()
            if seen_round >= context.round_num - self.config.frontier_memory_ttl
        }
        self.frontier_unknown_scores = {
            key: score
            for key, score in self.frontier_unknown_scores.items()
            if key in self.frontier_candidates
        }
        self.healthy_artery_tiles = {
            key: seen_round
            for key, seen_round in self.healthy_artery_tiles.items()
            if seen_round >= context.round_num - self.config.artery_memory_ttl
        }
        self.lane_congestion_observations = {
            key: value
            for key, value in self.lane_congestion_observations.items()
            if value[0] >= context.round_num - self.config.throughput_scan_freshness_rounds
        }

    def _mark_lane_failed(self, target: Position, context: TurnContext) -> None:
        self.failed_lanes[self._tile_key(target)] = BlacklistEntry(context.round_num + self.config.lane_blacklist_ttl)
        self.active_search_ticket = None
        self.micro_path = None

    def _lane_failed(self, target: Position) -> bool:
        return self._tile_key(target) in self.failed_lanes

    def _mark_splice_blocked(self, position: Position, context: TurnContext) -> None:
        self.blocked_splices[self._tile_key(position)] = BlacklistEntry(
            context.round_num + self.config.splice_blacklist_ttl
        )

    def _splice_blocked(self, position: Position) -> bool:
        return self._tile_key(position) in self.blocked_splices

    def _mark_loop_blacklist(self, position: Position, context: TurnContext) -> None:
        self.loop_blacklist[self._tile_key(position)] = BlacklistEntry(context.round_num + self.config.loop_blacklist_ttl)

    def _mark_congestion_blacklist(self, position: Position, context: TurnContext) -> None:
        self.congestion_blacklist[self._tile_key(position)] = BlacklistEntry(
            context.round_num + self.config.congestion_blacklist_ttl
        )

    def _is_move_blacklisted(self, position: Position) -> bool:
        key = self._tile_key(position)
        return key in self.loop_blacklist or key in self.congestion_blacklist

    def _map_center(self, context: TurnContext) -> Position:
        return Position(context.map_width // 2, context.map_height // 2)

    def _border_distance(self, context: TurnContext, position: Position) -> int:
        return min(
            position.x,
            position.y,
            (context.map_width - 1) - position.x,
            (context.map_height - 1) - position.y,
        )

    def _home_guard_target(self, context: TurnContext) -> Position:
        if self.anchor_position is None:
            return self._map_center(context)
        center = self._map_center(context)
        dx = 0 if center.x == self.anchor_position.x else (1 if center.x > self.anchor_position.x else -1)
        dy = 0 if center.y == self.anchor_position.y else (1 if center.y > self.anchor_position.y else -1)
        distance = 4 if self.observed_first_delivery_round is None else 6
        return Position(
            min(max(self.anchor_position.x + (dx * distance), 0), context.map_width - 1),
            min(max(self.anchor_position.y + (dy * distance), 0), context.map_height - 1),
        )

    def _deep_frontier_target(self, context: TurnContext) -> Position:
        if self.anchor_position is None:
            return Position(context.map_width - 1, context.map_height - 1)
        return Position(
            max(0, context.map_width - 1 - self.anchor_position.x),
            max(0, context.map_height - 1 - self.anchor_position.y),
        )

    def _exploration_focus(self, context: TurnContext) -> Position:
        if self.anchor_position is None:
            return self._map_center(context)
        center = self._map_center(context)
        cross_x = Position(center.x, self.anchor_position.y)
        cross_y = Position(self.anchor_position.x, center.y)
        if not self._economy_bootstrapped(context):
            if self._needs_early_ore_discovery(context):
                deep = self._deep_frontier_target(context)
                outward_x = Position((center.x + (2 * deep.x)) // 3, center.y)
                outward_y = Position(center.x, (center.y + (2 * deep.y)) // 3)
                outward_diag = Position(
                    min(max((self.anchor_position.x + (3 * deep.x)) // 4, 0), context.map_width - 1),
                    min(max((self.anchor_position.y + (3 * deep.y)) // 4, 0), context.map_height - 1),
                )
                outward_mid = Position(
                    min(max((center.x + deep.x) // 2, 0), context.map_width - 1),
                    min(max((center.y + deep.y) // 2, 0), context.map_height - 1),
                )
                options = [outward_x, outward_y, outward_diag, outward_mid, center]
                sweep_epoch = context.round_num // 36
            else:
                # Keep exploration anchored to home/center lanes until titanium
                # logistics are proven healthy.
                options = [center, cross_x, cross_y, self.anchor_position]
                sweep_epoch = 0
            return options[(context.entity_id + sweep_epoch) % len(options)]
        opposite = self.predicted_enemy_anchor or self._deep_frontier_target(context)
        mirrored_cross_x = Position(opposite.x, self.anchor_position.y)
        mirrored_cross_y = Position(self.anchor_position.x, opposite.y)
        options = [opposite, center, mirrored_cross_x, mirrored_cross_y]
        return options[context.entity_id % len(options)]

    def _friendly_builder_positions(self, context: TurnContext) -> list[Position]:
        self._reset_turn_caches(context)
        if self.turn_friendly_builder_positions_cache is not None:
            return self.turn_friendly_builder_positions_cache
        positions = [
            entity.position
            for entity in context.friendly_entities
            if entity.entity_type == EntityType.BUILDER_BOT and entity.entity_id != context.entity_id
        ]
        self.turn_friendly_builder_positions_cache = positions
        return positions

    def _friendly_spacing_penalty(
        self,
        context: TurnContext,
        position: Position,
        *,
        friendly_positions: list[Position] | None = None,
    ) -> tuple[int, int]:
        positions = friendly_positions if friendly_positions is not None else self._friendly_builder_positions(context)
        if not positions:
            return 0, 0
        adjacent = 0
        nearby = 0
        radius = self.config.dispersion_neighbor_radius
        for other in positions:
            distance = manhattan_distance(position, other)
            if distance <= 1:
                adjacent += 1
            elif distance <= radius:
                nearby += radius + 1 - distance
        return adjacent, nearby

    def _local_builder_congestion(self, context: TurnContext) -> bool:
        nearby = 0
        for other in self._friendly_builder_positions(context):
            if manhattan_distance(context.position, other) <= self.config.dispersion_congestion_radius:
                nearby += 1
                if nearby >= self.config.dispersion_congestion_threshold:
                    return True
        return False

    def _dispersed_exploration_target(self, context: TurnContext, target: Position) -> Position:
        friendly_positions = self._friendly_builder_positions(context)
        if not friendly_positions:
            return target
        nearest = min(
            friendly_positions,
            key=lambda position: (
                manhattan_distance(context.position, position),
                position.x,
                position.y,
            ),
        )
        nearest_distance = manhattan_distance(context.position, nearest)
        if nearest_distance > self.config.dispersion_neighbor_radius:
            return target
        dx = context.position.x - nearest.x
        dy = context.position.y - nearest.y
        step_x = 1 if dx > 0 else (-1 if dx < 0 else 0)
        step_y = 1 if dy > 0 else (-1 if dy < 0 else 0)
        if step_x == 0 and step_y == 0:
            if context.entity_id % 2 == 0:
                step_x = 1 if context.position.x <= context.map_width // 2 else -1
            else:
                step_y = 1 if context.position.y <= context.map_height // 2 else -1
        push_distance = self.config.dispersion_push_distance
        pushed_target = Position(
            min(max(context.position.x + (step_x * push_distance), 0), context.map_width - 1),
            min(max(context.position.y + (step_y * push_distance), 0), context.map_height - 1),
        )
        if nearest_distance <= 1:
            return pushed_target
        return Position(
            min(max((target.x * 2 + pushed_target.x) // 3, 0), context.map_width - 1),
            min(max((target.y * 2 + pushed_target.y) // 3, 0), context.map_height - 1),
        )

    def _patrol_mode(self, context: TurnContext) -> PatrolMode:
        if not self._economy_bootstrapped(context):
            return PatrolMode.DEEP_FRONTIER
        index = (self.patrol_cycle + (context.entity_id % 3)) % 3
        if context.round_num - self.observed_first_delivery_round < 120:
            if index != 1:
                return PatrolMode.DEEP_FRONTIER
        if index == 0:
            return PatrolMode.DEEP_FRONTIER
        if index == 1:
            return PatrolMode.MID_SWEEP
        return PatrolMode.HOME_GUARD

    def _advance_patrol_cycle(self) -> None:
        self.patrol_cycle = (self.patrol_cycle + 1) % 3

    def _decode_claim_marker(self, tile: TileInfo | None, context: TurnContext | None = None):
        if tile is None or tile.marker_value is None:
            return None
        message = decode_marker(tile.marker_value)
        if message is None or message.kind != MarkerKind.CLAIM_TITANIUM:
            return None
        return message

    def _lane_claim_with_age(
        self,
        tile: TileInfo | None,
        context: TurnContext,
    ) -> tuple[int, ClaimLaneStatus, int] | None:
        message = self._decode_claim_marker(tile)
        if message is None:
            return None
        decoded = decode_titanium_lane_status(message)
        if decoded is None:
            return None
        owner_id, status = decoded
        horizon = self.config.claim_horizon * (2 if status == ClaimLaneStatus.DONE else 1)
        if not is_recent_marker(context.round_num, message, horizon=horizon):
            return None
        return owner_id, status, marker_age(context.round_num, message)

    def _visible_lane_claim(self, tile: TileInfo | None, context: TurnContext) -> tuple[int, ClaimLaneStatus] | None:
        claim = self._lane_claim_with_age(tile, context)
        if claim is None:
            return None
        owner_id, status, _age = claim
        return owner_id, status

    def _claim_status_for_target(self, context: TurnContext, target: Position) -> ClaimLaneStatus:
        memory = self.ore_memory.get(target)
        if (
            memory is not None
            and memory.has_friendly_harvester
            and memory.last_harvester_round >= context.round_num - self.config.claim_refresh_turns
            and memory.last_healthy_round >= context.round_num - self.config.route_memory_ttl
        ):
            return ClaimLaneStatus.DONE
        if self.current_lane_target == target and (
            self.pending_harvester is not None
            or self.builder_state == BuilderStateV3.ROUTE_HOME_SAFE
            or self.route_resume_target is not None
        ):
            return ClaimLaneStatus.ROUTING
        return ClaimLaneStatus.CLAIMED

    def _lane_claim_blocks_target(self, context: TurnContext, ore_position: Position) -> bool:
        self._reset_turn_caches(context)
        key = self._tile_key(ore_position)
        if key in self.turn_lane_claim_block_cache:
            return self.turn_lane_claim_block_cache[key]
        tile = context.tiles.get(ore_position)
        if tile is None:
            self.turn_lane_claim_block_cache[key] = False
            return False
        claim = self._visible_lane_claim(tile, context)
        if claim is None:
            self.turn_lane_claim_block_cache[key] = False
            return False
        owner_id, status = claim
        if owner_id == context.entity_id:
            self.turn_lane_claim_block_cache[key] = False
            return False
        # Suppress duplicate lane work from foreign builders. DONE lanes are also
        # treated as claimed for selection so builders avoid rebuilding settled
        # arteries.
        blocked = status in (
            ClaimLaneStatus.CLAIMED,
            ClaimLaneStatus.ROUTING,
            ClaimLaneStatus.DONE,
            ClaimLaneStatus.REPAIR,
        )
        self.turn_lane_claim_block_cache[key] = blocked
        return blocked

    def _has_fresher_foreign_lane_owner(self, context: TurnContext, ore_position: Position) -> bool:
        tile = context.tiles.get(ore_position)
        claim = self._lane_claim_with_age(tile, context)
        if claim is None:
            return False
        owner_id, status, foreign_age = claim
        if owner_id == context.entity_id:
            return False
        if status not in (ClaimLaneStatus.CLAIMED, ClaimLaneStatus.ROUTING):
            return False
        if self.last_claim_target != ore_position or self.last_claim_round < 0:
            return True
        own_age = max(0, context.round_num - self.last_claim_round)
        return foreign_age <= own_age

    def _repair_owner_for_ore(self, context: TurnContext, ore_position: Position) -> int | None:
        tile = context.tiles.get(ore_position)
        claim = self._lane_claim_with_age(tile, context)
        if claim is None:
            return None
        owner_id, status, _age = claim
        if status != ClaimLaneStatus.REPAIR:
            return None
        return owner_id

    def _claim_marker(
        self,
        context: TurnContext,
        target: Position | None,
        *,
        status: ClaimLaneStatus | None = None,
    ) -> MarkerDecision | None:
        if target is None:
            return None
        claim_status = status or self._claim_status_for_target(context, target)
        marker_value = encode_titanium_lane_status(context.entity_id, claim_status, context.round_num)
        tile = context.tiles.get(target)
        if tile is not None:
            claim = self._visible_lane_claim(tile, context)
            if claim is not None and claim == (context.entity_id, claim_status):
                return None
        if (
            self.last_claim_target == target
            and context.round_num - self.last_claim_round < self.config.claim_refresh_turns
        ):
            return None
        self.last_claim_target = target
        self.last_claim_round = context.round_num
        return MarkerDecision(target, marker_value)

    def _scaled_titanium_cost(self, base_cost: tuple[int, int], context: TurnContext) -> int:
        return math.ceil(base_cost[0] * (context.scale_percent / 100.0))

    def _builder_cost(self, context: TurnContext) -> int:
        return self._scaled_titanium_cost(GameConstants.BUILDER_BOT_BASE_COST, context)

    def _harvester_cost(self, context: TurnContext) -> int:
        return self._scaled_titanium_cost(GameConstants.HARVESTER_BASE_COST, context)

    def _conveyor_cost(self, context: TurnContext) -> int:
        return self._scaled_titanium_cost(GameConstants.CONVEYOR_BASE_COST, context)

    def _bridge_cost(self, context: TurnContext) -> int:
        return self._scaled_titanium_cost(GameConstants.BRIDGE_BASE_COST, context)

    def _road_cost(self, context: TurnContext) -> int:
        return self._scaled_titanium_cost(GameConstants.ROAD_BASE_COST, context)

    def _gunner_cost(self, context: TurnContext) -> int:
        return self._scaled_titanium_cost(GameConstants.GUNNER_BASE_COST, context)

    def _gunner_rotate_cost(self, context: TurnContext) -> int:
        return self._scaled_titanium_cost(GameConstants.GUNNER_ROTATE_COST, context)

    def _first_lane_reserve(self, context: TurnContext) -> int:
        return self._harvester_cost(context) + (self._conveyor_cost(context) * 4)

    def _visible_titanium_harvester_count(self, context: TurnContext) -> int:
        count = 0
        for ore_position in context.visible_ore_tiles:
            tile = context.tiles.get(ore_position)
            if tile is None or tile.environment != Environment.ORE_TITANIUM:
                continue
            if tile.building_type == EntityType.HARVESTER and tile.building_team == context.team:
                count += 1
        return count

    def _known_titanium_ore_count(self, context: TurnContext) -> int:
        cutoff = context.round_num - self.config.ore_memory_ttl
        known = {
            memory.position
            for memory in self.ore_memory.values()
            if memory.environment == Environment.ORE_TITANIUM
            and memory.last_seen_round >= cutoff
        }
        for ore_position in context.visible_ore_tiles:
            tile = context.tiles.get(ore_position)
            if tile is not None and tile.environment == Environment.ORE_TITANIUM:
                known.add(ore_position)
        return len(known)

    def _needs_early_ore_discovery(self, context: TurnContext) -> bool:
        if self.observed_first_delivery_round is not None and self._economy_bootstrapped(context):
            return False
        if context.round_num > self.config.early_exploration_round:
            return False
        return self._known_titanium_ore_count(context) < self.config.early_exploration_ore_target

    def _core_visible_titanium_ore_count(self, context: TurnContext) -> int:
        return sum(
            1
            for ore_position in context.visible_ore_tiles
            if (tile := context.tiles.get(ore_position)) is not None
            and tile.environment == Environment.ORE_TITANIUM
        )

    def _core_needs_early_spawn_pressure(self, context: TurnContext) -> bool:
        if self.observed_first_delivery_round is not None:
            return False
        if context.round_num > self.config.core_spawn_pressure_round:
            return False
        return self._core_visible_titanium_ore_count(context) < self.config.core_spawn_pressure_visible_ore_target

    def _pre_delivery_spawn_cap(self, context: TurnContext) -> int:
        if not self._core_needs_early_spawn_pressure(context):
            return self.config.pre_delivery_spawn_cap_default
        if context.round_num < 50:
            return min(self.config.pre_delivery_spawn_cap_discovery_early, 7)
        if context.round_num < 120:
            return min(self.config.pre_delivery_spawn_cap_discovery_mid, 8)
        return min(self.config.pre_delivery_spawn_cap_discovery_late, 9)

    def _spawn_cap(self, context: TurnContext) -> int:
        if self._core_needs_early_spawn_pressure(context):
            if context.round_num < 20:
                return 5
            if context.round_num < 60:
                return 8
            if context.round_num < 140:
                return 10
        if context.round_num < 20:
            return 4
        if context.round_num < 60:
            return 7
        if context.round_num < 140:
            return 10
        visible_harvesters = self._visible_titanium_harvester_count(context)
        floor_cap = 8
        if self.observed_first_delivery_round is not None:
            rounds_since_delivery = max(0, context.round_num - self.observed_first_delivery_round)
            if rounds_since_delivery >= 180:
                floor_cap = 10
            if rounds_since_delivery >= 420:
                floor_cap = 12
        elif context.round_num >= 400:
            floor_cap = 9
        return min(14, max(floor_cap, 2 * visible_harvesters + 2))

    def choose_spawn_position(self, context: TurnContext) -> Position | None:
        candidates = [
            tile.position
            for tile in context.tiles.values()
            if tile.building_type == EntityType.CORE
            and tile.building_team == context.team
            and tile.builder_bot_id in (None, context.entity_id)
        ]
        if not candidates:
            return None
        titanium_targets = [
            ore_position
            for ore_position in context.visible_ore_tiles
            if (tile := context.tiles.get(ore_position)) is not None
            and tile.environment == Environment.ORE_TITANIUM
        ]
        target = (
            min(
                titanium_targets,
                key=lambda ore_position: (
                    manhattan_distance(context.position, ore_position),
                    ore_position.x,
                    ore_position.y,
                ),
            )
            if titanium_targets
            else self._map_center(context)
        )
        candidates.sort(
            key=lambda position: (
                manhattan_distance(position, target),
                (position.x + position.y + context.round_num) % 4,
                position.x,
                position.y,
            )
        )
        best_distance = manhattan_distance(candidates[0], target)
        best = [position for position in candidates if manhattan_distance(position, target) == best_distance]
        best.sort(key=lambda position: (position.x, position.y))
        return best[(context.round_num + context.entity_id) % len(best)]

    def _core_repair_or_conversion_pressure(self, context: TurnContext) -> bool:
        reports = self._scan_visible_titanium_route_health(context) if self._has_visible_team_titanium_harvester(context) else []
        if any(
            report.status in (RouteHealth.REPAIRABLE_FAULT, RouteHealth.CONGESTED)
            for report in reports
        ):
            return True
        core_tiles = [
            tile.position
            for tile in context.tiles.values()
            if tile.building_type == EntityType.CORE and tile.building_team == context.team
        ]
        if not core_tiles:
            return False
        for ore_position in context.visible_ore_tiles:
            ore_tile = context.tiles.get(ore_position)
            if ore_tile is None or ore_tile.environment != Environment.ORE_TITANIUM:
                continue
            if ore_tile.building_type == EntityType.HARVESTER and ore_tile.building_team == context.team:
                continue
            goals = [
                goal
                for goal in (
                    ore_position.add(Direction.NORTH),
                    ore_position.add(Direction.SOUTH),
                    ore_position.add(Direction.EAST),
                    ore_position.add(Direction.WEST),
                )
                if self._in_bounds(context, goal)
            ]
            if not goals:
                continue
            for core_tile in core_tiles:
                if manhattan_distance(core_tile, ore_position) <= 8:
                    path = find_path_to_visible_goal(context, core_tile, set(goals), max_nodes=64)
                    if path and len(path) <= 8:
                        return True
        return False

    def _core_axionite_reserve(self, context: TurnContext) -> int:
        under_threat = any(enemy.entity_type in self.TURRET_TYPES for enemy in context.enemy_entities)
        return self.config.axionite_threat_reserve if under_threat else self.config.axionite_idle_reserve

    def _planned_convert_amount(self, context: TurnContext, reports: list[LaneHealthReport]) -> int:
        if not self.capabilities.supports_convert or context.action_cooldown != 0:
            return 0
        reserve = self._core_axionite_reserve(context)
        if context.axionite <= reserve:
            return 0
        if self.observed_first_delivery_round is None:
            return 0
        titanium_pressure = self._core_repair_or_conversion_pressure(context) or (
            context.titanium < max(self._builder_cost(context), self._first_lane_reserve(context))
        )
        if not titanium_pressure:
            return 0
        spare_axionite = context.axionite - reserve
        titanium_shortfall = max(
            max(self._builder_cost(context), self._first_lane_reserve(context)) - context.titanium,
            4,
        )
        return max(0, min(spare_axionite, math.ceil(titanium_shortfall / 4)))

    def _decide_core(self, context: TurnContext) -> TurnPlan:
        reports = self._scan_visible_titanium_route_health(context) if self._should_scan_route_health(context) else []
        spawn_position = self.choose_spawn_position(context)
        convert_amount = self._planned_convert_amount(context, reports)
        builder_cost = self._builder_cost(context)
        first_lane_reserve = self._first_lane_reserve(context)
        if spawn_position is None:
            if convert_amount > 0:
                return TurnPlan(action=ConvertDecision(convert_amount), note="policy_fsm_v3 core convert idle")
            return TurnPlan(note="policy_fsm_v3 core hold")
        spawn_cap = min(GameConstants.MAX_TEAM_UNITS, self._spawn_cap(context))
        if context.unit_count >= spawn_cap:
            if convert_amount > 0:
                return TurnPlan(action=ConvertDecision(convert_amount), note="policy_fsm_v3 core convert capped")
            return TurnPlan(note="policy_fsm_v3 core hold cap")
        if context.unit_count >= 44 and not self._core_repair_or_conversion_pressure(context):
            if convert_amount > 0:
                return TurnPlan(action=ConvertDecision(convert_amount), note="policy_fsm_v3 core convert high-cap")
            return TurnPlan(note="policy_fsm_v3 core hold high-cap")
        pre_delivery_spawn_cap = self._pre_delivery_spawn_cap(context)
        if (
            self.observed_first_delivery_round is None
            and context.unit_count >= pre_delivery_spawn_cap
            and not self._core_repair_or_conversion_pressure(context)
        ):
            return TurnPlan(note="policy_fsm_v3 core hold pre-delivery cap")
        if (
            self.observed_first_delivery_round is None
            and context.unit_count >= pre_delivery_spawn_cap
            and context.titanium - builder_cost < first_lane_reserve
        ):
            soft_lane_reserve = self._harvester_cost(context) + (
                self._conveyor_cost(context) * self.config.pre_delivery_soft_lane_reserve_conveyors
            )
            if not (
                self._core_needs_early_spawn_pressure(context)
                and context.titanium - builder_cost >= soft_lane_reserve
            ):
                return TurnPlan(note="policy_fsm_v3 core hold lane reserve")
        if context.titanium < builder_cost:
            if convert_amount > 0:
                return TurnPlan(action=ConvertDecision(convert_amount), note="policy_fsm_v3 core convert for spawn")
            return TurnPlan(note="policy_fsm_v3 core hold unaffordable")
        self.last_core_spend_round = context.round_num
        self.last_core_spend = builder_cost
        return TurnPlan(
            action=BuildDecision(BuildKind.BUILDER_BOT, spawn_position),
            note="policy_fsm_v3 core spawn",
        )

    def _visible_enemy_threat(
        self,
        context: TurnContext,
        *,
        protected: set[Position] | None = None,
    ) -> EntityInfo | None:
        best: tuple[int, EntityInfo] | None = None
        protected_positions = protected if protected is not None else self._protected_positions(context)
        for enemy in context.enemy_entities:
            if enemy.entity_type not in self.TURRET_TYPES and enemy.entity_type != EntityType.BUILDER_BOT:
                continue
            local_distance = manhattan_distance(context.position, enemy.position)
            if local_distance > self.config.defend_radius:
                artery_threat = any(
                    manhattan_distance(enemy.position, position) <= 1 for position in protected_positions
                )
                if not artery_threat:
                    continue
            else:
                artery_threat = False
            score = local_distance - (2 if artery_threat else 0)
            if best is None or score < best[0]:
                best = (score, enemy)
        return None if best is None else best[1]

    def _protected_positions(self, context: TurnContext) -> set[Position]:
        protected = set(self.trail[-5:])
        protected.update(self._logistics_positions(context))
        return protected

    def _choose_defend_plan(self, context: TurnContext) -> TurnPlan | None:
        profile_start = perf_counter_ns() if self.profile_enabled else None
        result: TurnPlan | None = None
        if not self._economy_bootstrapped(context):
            if profile_start is not None:
                self._profile_record("choose_defend_plan", perf_counter_ns() - profile_start)
            return None
        if not context.enemy_entities:
            if profile_start is not None:
                self._profile_record("choose_defend_plan", perf_counter_ns() - profile_start)
            return None
        gunner_cost = self._gunner_cost(context)
        if context.titanium < max(self.config.defend_titanium_threshold, gunner_cost):
            result = None
        else:
            protected = self._protected_positions(context)
            enemy = self._visible_enemy_threat(context, protected=protected)
            if enemy is not None:
                build_direction = context.position.direction_to(enemy.position)
                candidate_positions = []
                for direction in CARDINAL_DIRECTIONS:
                    position = context.position.add(direction)
                    tile = context.tiles.get(position)
                    if tile is None or tile.environment != Environment.EMPTY:
                        continue
                    if tile.building_type is not None and tile.building_team not in (None, context.team):
                        continue
                    if tile.building_type in self.TURRET_TYPES:
                        continue
                    if position in protected:
                        continue
                    candidate_positions.append(position)
                allowed_positions, _ = self._build_allowed_candidates(
                    context,
                    candidate_positions,
                    kind=BuildKind.GUNNER,
                    direction=build_direction,
                    replace_existing=True,
                )
                if allowed_positions:
                    position = min(
                        allowed_positions,
                        key=lambda candidate: (
                            manhattan_distance(candidate, enemy.position),
                            self._recent_visit_count(candidate),
                            candidate.x,
                            candidate.y,
                        ),
                    )
                    tile = context.tiles.get(position)
                    replace_existing = tile is not None and tile.building_type in (EntityType.ROAD, EntityType.MARKER)
                    result = TurnPlan(
                        action=BuildDecision(
                            kind=BuildKind.GUNNER,
                            position=position,
                            direction=build_direction,
                            replace_existing=replace_existing,
                        ),
                        note="policy_fsm_v3 reactive defend",
                    )
        if profile_start is not None:
            self._profile_record("choose_defend_plan", perf_counter_ns() - profile_start)
        return result

    def _decide_turret(self, context: TurnContext) -> TurnPlan:
        visible_targets = list(context.enemy_entities)
        if self.capabilities.supports_get_attackable_tiles:
            attackable = set(context.attackable_tiles)
            visible_targets = [entity for entity in visible_targets if entity.position in attackable]
        if visible_targets:
            target = min(
                visible_targets,
                key=lambda entity: (
                    0 if entity.entity_type in self.TURRET_TYPES else 1,
                    entity.hp,
                    manhattan_distance(context.position, entity.position),
                    entity.position.x,
                    entity.position.y,
                ),
            )
            return TurnPlan(action=FireDecision(target.position), note="policy_fsm_v3 turret fire")
        rotate_direction = self._choose_gunner_rotate(context)
        if rotate_direction is not None:
            return TurnPlan(action=RotateDecision(rotate_direction), note="policy_fsm_v3 gunner rotate")
        return TurnPlan(note="policy_fsm_v3 turret hold")

    def _choose_gunner_rotate(self, context: TurnContext) -> Direction | None:
        if not self.capabilities.supports_rotate or context.entity_type != EntityType.GUNNER:
            return None
        if context.action_cooldown != 0 or context.titanium < self._gunner_rotate_cost(context):
            return None
        current_entity = context.entities.get(context.entity_id)
        if current_entity is None or current_entity.direction is None or not context.enemy_entities:
            return None
        current_direction = current_entity.direction
        left = current_direction.rotate_left()
        right = current_direction.rotate_right()
        for enemy in sorted(
            context.enemy_entities,
            key=lambda entity: (
                0 if entity.entity_type in self.TURRET_TYPES else 1,
                manhattan_distance(context.position, entity.position),
                entity.position.x,
                entity.position.y,
            ),
        ):
            desired = context.position.direction_to(enemy.position)
            if desired == left:
                return left
            if desired == right:
                return right
        return None

    def _update_symmetry_hypothesis(self, context: TurnContext) -> None:
        if not self.belief_tiles:
            return
        mode_scores: dict[str, tuple[int, int]] = {}
        ordered_beliefs = sorted(
            self.belief_tiles.items(),
            key=lambda item: (item[0].x, item[0].y),
        )
        for mode in sorted(self.symmetry_candidates):
            compared = 0
            mismatches = 0
            for position, belief in ordered_beliefs:
                mirrored = self._mirror_position(context, position, mode)
                mirrored_belief = self.belief_tiles.get(mirrored)
                if mirrored_belief is None:
                    continue
                compared += 1
                if belief.environment != mirrored_belief.environment:
                    mismatches += 1
                if compared >= 160:
                    break
            mode_scores[mode] = (compared, mismatches)
        next_candidates: set[str] = set()
        for mode, (compared, mismatches) in mode_scores.items():
            if compared < 8 or mismatches * 4 <= compared:
                next_candidates.add(mode)
        if next_candidates:
            self.symmetry_candidates = next_candidates
        ranked = sorted(
            (
                (mismatches / compared if compared else 1.0, -compared, mode)
                for mode, (compared, mismatches) in mode_scores.items()
                if mode in self.symmetry_candidates
            )
        )
        self.symmetry_mode = ranked[0][2] if ranked else None
        if self.anchor_position is not None and self.symmetry_mode is not None:
            self.predicted_enemy_anchor = self._mirror_position(context, self.anchor_position, self.symmetry_mode)

    def _mirror_position(self, context: TurnContext, position: Position, mode: str) -> Position:
        max_x = context.map_width - 1
        max_y = context.map_height - 1
        if mode == "ROT180":
            return Position(max_x - position.x, max_y - position.y)
        if mode == "MIRROR_X":
            return Position(max_x - position.x, position.y)
        return Position(position.x, max_y - position.y)

    def _update_belief_memory(self, context: TurnContext) -> None:
        profile_start = perf_counter_ns() if self.profile_enabled else None
        tile_memory_changed = False
        ore_memory_changed = False
        remaining_us = self._planner_remaining_us(context)
        full_resync_due = (
            self.last_full_belief_resync_round < 0
            or context.round_num - self.last_full_belief_resync_round >= self.full_belief_resync_period
        )
        full_resync = full_resync_due and (
            remaining_us >= self.config.full_belief_resync_min_remaining_us
        )
        track_frontier = (
            remaining_us >= self.config.frontier_belief_min_remaining_us
            and self.current_lane_target is None
            and (
            self.builder_state in {BuilderStateV3.FRONTIER_PUSH, BuilderStateV3.PATROL}
            or (self.micro_path is not None and self.micro_path.kind == SearchKind.FRONTIER)
            )
            and (
                self.frontier_waypoint_cache is None
                or self.frontier_waypoint_cache == context.position
                or self.frontier_waypoint_cache_round < context.round_num - 3
            )
        )
        frontier_track_remaining = self.config.frontier_track_tile_cap if track_frontier else 0
        if full_resync:
            for memory in self.ore_memory.values():
                if memory.last_seen_round < context.round_num - 3 and memory.has_friendly_harvester:
                    memory.has_friendly_harvester = False
                    ore_memory_changed = True
            self.last_full_belief_resync_round = context.round_num
        visible_tiles = context.tiles.values()
        if frontier_track_remaining > 0:
            # Frontier caching has a hard per-turn cap; keep the sampled tiles
            # deterministic so target churn does not depend on dict ordering.
            visible_tiles = sorted(
                visible_tiles,
                key=lambda tile: (tile.position.x, tile.position.y),
            )
        for tile in visible_tiles:
            direction = None
            bridge_target = None
            if tile.building_type in (EntityType.CONVEYOR, EntityType.BRIDGE) and tile.building_id is not None:
                entity = context.entities.get(tile.building_id)
                if entity is not None:
                    direction = entity.direction
                    bridge_target = entity.bridge_target
            existing = self.belief_tiles.get(tile.position)
            occupied_round = (
                context.round_num
                if tile.builder_bot_id not in (None, context.entity_id)
                else (existing.last_occupied_round if existing is not None else -9999)
            )
            if existing is None:
                tile_memory_changed = True
                self.belief_tiles[tile.position] = BeliefTile(
                    environment=tile.environment,
                    building_type=tile.building_type,
                    building_team=tile.building_team,
                    direction=direction,
                    last_seen_round=context.round_num,
                    last_occupied_round=occupied_round,
                    bridge_target=bridge_target,
                )
            else:
                if (
                    existing.environment != tile.environment
                    or existing.building_type != tile.building_type
                    or existing.building_team != tile.building_team
                    or existing.direction != direction
                    or existing.bridge_target != bridge_target
                ):
                    tile_memory_changed = True
                existing.environment = tile.environment
                existing.building_type = tile.building_type
                existing.building_team = tile.building_team
                existing.direction = direction
                existing.last_seen_round = context.round_num
                existing.last_occupied_round = occupied_round
                existing.bridge_target = bridge_target
            if frontier_track_remaining > 0 and self._tile_passable_for_route(tile):
                frontier_unknowns = unknown_neighbor_count(context, tile.position)
                if frontier_unknowns > 0:
                    key = self._tile_key(tile.position)
                    self.frontier_candidates[key] = context.round_num
                    self.frontier_unknown_scores[key] = frontier_unknowns
                    frontier_track_remaining -= 1
            if tile.environment in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                memory = self.ore_memory.get(tile.position)
                if memory is None:
                    memory = OreMemory(
                        position=tile.position,
                        environment=tile.environment,
                        last_seen_round=context.round_num,
                    )
                    self.ore_memory[tile.position] = memory
                    ore_memory_changed = True
                memory.environment = tile.environment
                memory.last_seen_round = context.round_num
                if tile.building_type == EntityType.HARVESTER and tile.building_team == context.team:
                    if not memory.has_friendly_harvester:
                        ore_memory_changed = True
                    memory.has_friendly_harvester = True
                    memory.last_harvester_round = context.round_num
                elif memory.last_harvester_round < context.round_num - 3:
                    if memory.has_friendly_harvester:
                        ore_memory_changed = True
                    memory.has_friendly_harvester = False

        self._expire_memory(context)
        self.ore_memory_dirty = self.ore_memory_dirty or ore_memory_changed
        self.symmetry_dirty = self.symmetry_dirty or tile_memory_changed
        should_rebuild_clusters = not self.ore_clusters or (
            self.ore_memory_dirty
            and context.round_num - self.last_ore_cluster_rebuild_round >= self.config.ore_cluster_rebuild_interval
        )
        if should_rebuild_clusters:
            rebuild_start = perf_counter_ns() if self.profile_enabled else None
            self._rebuild_ore_clusters(context)
            if rebuild_start is not None:
                self._profile_record("rebuild_ore_clusters", perf_counter_ns() - rebuild_start)
            self.last_ore_cluster_rebuild_round = context.round_num
            self.ore_memory_dirty = False
        if (
            self.symmetry_dirty
            and context.round_num - self.last_symmetry_update_round >= self.config.symmetry_update_interval
            and remaining_us >= self.config.symmetry_update_min_remaining_us
        ):
            self._update_symmetry_hypothesis(context)
            self.last_symmetry_update_round = context.round_num
            self.symmetry_dirty = False
        self.last_belief_update_round = context.round_num
        if profile_start is not None:
            self._profile_record("update_belief_memory", perf_counter_ns() - profile_start)

    def _rebuild_ore_clusters(self, context: TurnContext) -> None:
        titanium_by_key = {
            self._tile_key(memory.position): memory
            for memory in self.ore_memory.values()
            if memory.environment == Environment.ORE_TITANIUM
            and memory.last_seen_round >= context.round_num - self.config.ore_memory_ttl
        }
        if not titanium_by_key:
            self.ore_clusters = []
            return
        clusters: list[OreCluster] = []
        unvisited = set(titanium_by_key)
        while unvisited:
            seed_key = min(unvisited)
            queue: deque[tuple[int, int]] = deque([seed_key])
            members: list[Position] = []
            newest = -1
            while queue:
                current_key = queue.popleft()
                if current_key not in unvisited:
                    continue
                unvisited.remove(current_key)
                ore = titanium_by_key[current_key]
                members.append(ore.position)
                newest = max(newest, ore.last_seen_round)
                cx, cy = current_key
                for dx, dy in MANHATTAN_RADIUS2_OFFSETS:
                    neighbor_key = (cx + dx, cy + dy)
                    if neighbor_key in unvisited:
                        queue.append(neighbor_key)
            if not members:
                continue
            cx = sum(position.x for position in members) // len(members)
            cy = sum(position.y for position in members) // len(members)
            clusters.append(
                OreCluster(
                    centroid=Position(cx, cy),
                    members=sorted(members, key=lambda position: (position.x, position.y)),
                    last_seen_round=newest,
                )
            )
        clusters.sort(
            key=lambda cluster: (
                -len(cluster.members),
                -cluster.last_seen_round,
                cluster.centroid.x,
                cluster.centroid.y,
            )
        )
        self.ore_clusters = clusters

    def _tile_passable_for_route(self, tile: TileInfo | None) -> bool:
        if tile is None:
            return False
        if tile.environment == Environment.WALL:
            return False
        if tile.environment in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
            return tile.building_type == EntityType.CORE
        if tile.building_type in (
            None,
            EntityType.ROAD,
            EntityType.MARKER,
            EntityType.CONVEYOR,
            EntityType.BRIDGE,
            EntityType.CORE,
        ):
            return True
        return False

    def _planner_passable(self, context: TurnContext, position: Position) -> bool:
        if not self._in_bounds(context, position):
            return False
        if self._is_move_blacklisted(position):
            return False
        tile = context.tiles.get(position)
        if tile is not None:
            if not self._tile_passable_for_route(tile):
                return False
            if tile.builder_bot_id not in (None, context.entity_id):
                return False
            return True
        belief = self.belief_tiles.get(position)
        if belief is None:
            return True
        if belief.last_seen_round < context.round_num - self.config.ore_memory_ttl:
            return True
        if belief.environment == Environment.WALL:
            return False
        if belief.environment in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
            return belief.building_type == EntityType.CORE
        if belief.building_type in (
            EntityType.BARRIER,
            EntityType.GUNNER,
            EntityType.SENTINEL,
            EntityType.BREACH,
            EntityType.LAUNCHER,
            EntityType.HARVESTER,
            EntityType.FOUNDRY,
        ):
            return False
        if belief.last_occupied_round >= context.round_num - self.config.occupancy_memory_ttl:
            return False
        return True

    def _build_action_mask(self, context: TurnContext, goal: Position) -> ActionMask:
        mask = ActionMask()
        previous = self.recent_positions[-2] if len(self.recent_positions) >= 2 else None
        reversal_candidates: list[Direction] = []
        move_ready_adjacent_count = None
        allow_diagonal_bridge_build = (
            self.builder_state == BuilderStateV3.ROUTE_HOME_SAFE
            or self.route_resume_target is not None
        )
        if (
            self.observed_first_delivery_round is None
            and self.builder_state not in (BuilderStateV3.CLAIM_TITANIUM, BuilderStateV3.ROUTE_HOME_SAFE)
        ):
            move_ready_adjacent_count = self._move_ready_adjacent_count(context)
        for direction in CARDINAL_DIRECTIONS:
            candidate = context.position.add(direction)
            if not self._in_bounds(context, candidate):
                mask.blocked_moves[direction] = "off_map"
                continue
            tile = context.tiles.get(candidate)
            if tile is not None and tile.environment == Environment.WALL:
                mask.blocked_moves[direction] = "wall"
                continue
            if tile is not None and tile.builder_bot_id not in (None, context.entity_id):
                mask.blocked_moves[direction] = "occupied"
                self._mark_congestion_blacklist(candidate, context)
                continue
            if self._is_move_blacklisted(candidate):
                mask.blocked_moves[direction] = "blacklist"
                continue
            if (
                previous is not None
                and candidate == previous
                and self._is_ping_pong()
                and self._recent_visit_count(candidate) >= 2
            ):
                mask.blocked_moves[direction] = "dead_reversal"
                reversal_candidates.append(direction)
                continue
            if not self._planner_passable(context, candidate):
                mask.blocked_moves[direction] = "blocked"
                continue
            if not self._fast_step_move_feasible(
                context,
                candidate,
                tile=tile,
                move_ready_adjacent_count=move_ready_adjacent_count,
            ):
                mask.blocked_moves[direction] = "no_ground_budget"
                continue
            mask.allowed_moves[direction] = candidate
        if not mask.allowed_moves and reversal_candidates:
            for direction in reversal_candidates:
                candidate = context.position.add(direction)
                tile = context.tiles.get(candidate)
                if self._fast_step_move_feasible(
                    context,
                    candidate,
                    tile=tile,
                    move_ready_adjacent_count=move_ready_adjacent_count,
                ):
                    mask.allowed_moves[direction] = candidate
                    mask.blocked_moves.pop(direction, None)
        if not mask.allowed_moves:
            for direction in DIAGONAL_DIRECTIONS:
                candidate = context.position.add(direction)
                if not self._in_bounds(context, candidate):
                    continue
                tile = context.tiles.get(candidate)
                if tile is None:
                    continue
                if tile.environment == Environment.WALL:
                    continue
                if tile.builder_bot_id not in (None, context.entity_id):
                    continue
                if tile.building_team not in (None, context.team):
                    continue
                if self._tile_move_ready(tile):
                    mask.allowed_moves[direction] = candidate
                    continue
                if self._ground_build_allowed_fast(
                    context,
                    candidate,
                    tile,
                    move_ready_adjacent_count=move_ready_adjacent_count,
                ):
                    mask.allowed_moves[direction] = candidate
                    continue
                if not allow_diagonal_bridge_build:
                    continue
                if tile.building_type in self.PROTECTED_LOGISTICS:
                    continue
                if tile.building_type not in (None, EntityType.ROAD, EntityType.MARKER):
                    continue
                if context.titanium < self._bridge_cost(context):
                    continue
                mask.allowed_moves[direction] = candidate
        return mask

    def _build_allowed_candidates(
        self,
        context: TurnContext,
        positions: list[Position],
        *,
        kind: BuildKind,
        direction: Direction | None = None,
        replace_existing: bool,
        allow_protected_rewrite: bool = False,
    ) -> tuple[list[Position], dict[Position, str]]:
        blocked: dict[Position, str] = {}
        allowed: list[Position] = []
        protected_candidates: list[Position] = []
        for position in positions:
            tile = context.tiles.get(position)
            if tile is None:
                blocked[position] = "missing"
                continue
            if tile.environment != Environment.EMPTY:
                blocked[position] = "invalid_geometry"
                continue
            if tile.building_type is not None and tile.building_team not in (None, context.team):
                blocked[position] = "enemy_occupied"
                continue
            if self._splice_blocked(position) and kind == BuildKind.CONVEYOR:
                blocked[position] = "splice_blacklist"
                continue
            can_rewrite_protected = (
                allow_protected_rewrite
                and replace_existing
                and tile.building_team == context.team
                and tile.building_type in (EntityType.CONVEYOR, EntityType.BRIDGE)
            )
            if (
                replace_existing
                and tile.building_team == context.team
                and tile.building_type in self.PROTECTED_LOGISTICS
                and not can_rewrite_protected
            ):
                blocked[position] = "sacred_logistics"
                continue
            if (
                tile.building_team == context.team
                and tile.building_type in self.PROTECTED_LOGISTICS
                and kind != BuildKind.HARVESTER
                and not can_rewrite_protected
            ):
                blocked[position] = "sacred_logistics"
                continue
            if kind == BuildKind.CONVEYOR and direction is not None:
                output = position.add(direction)
                if not self._in_bounds(context, output):
                    blocked[position] = "invalid_geometry"
                    continue
                out_tile = context.tiles.get(output)
                if out_tile is not None and out_tile.environment == Environment.WALL:
                    blocked[position] = "invalid_geometry"
                    continue
            key = self._tile_key(position)
            if key in self.healthy_artery_tiles:
                protected_candidates.append(position)
            allowed.append(position)

        non_protected = [position for position in allowed if position not in protected_candidates]
        if non_protected and protected_candidates:
            for position in protected_candidates:
                blocked[position] = "protected_artery"
            allowed = non_protected
        return allowed, blocked

    def _safe_ground_action(self, position: Position, context: TurnContext) -> BuildDecision | None:
        if (
            self.observed_first_delivery_round is None
            and context.titanium <= self._first_lane_reserve(context)
        ):
            if context.titanium < self._road_cost(context):
                return None
            if self.builder_state not in (BuilderStateV3.CLAIM_TITANIUM, BuilderStateV3.ROUTE_HOME_SAFE):
                if self._move_ready_adjacent_count(context) > 1:
                    return None
        tile = context.tiles.get(position)
        if tile is None or tile.environment != Environment.EMPTY:
            return None
        candidates = [position]
        replace_existing = tile.building_type == EntityType.MARKER
        allowed, _ = self._build_allowed_candidates(
            context,
            candidates,
            kind=BuildKind.ROAD,
            replace_existing=replace_existing,
        )
        if not allowed:
            return None
        if tile.building_type is None:
            return BuildDecision(BuildKind.ROAD, position)
        if tile.building_type == EntityType.MARKER:
            return BuildDecision(BuildKind.ROAD, position, replace_existing=True)
        return None

    def _tile_move_ready(self, tile: TileInfo | None) -> bool:
        if tile is None:
            return False
        if tile.environment in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
            return tile.building_type == EntityType.CORE
        return tile.building_type in (
            EntityType.ROAD,
            EntityType.MARKER,
            EntityType.CONVEYOR,
            EntityType.BRIDGE,
            EntityType.CORE,
        )

    def _move_ready_adjacent_count(self, context: TurnContext) -> int:
        count = 0
        for direction in CARDINAL_DIRECTIONS:
            position = context.position.add(direction)
            if not self._in_bounds(context, position):
                continue
            tile = context.tiles.get(position)
            if tile is None:
                continue
            if tile.builder_bot_id not in (None, context.entity_id):
                continue
            if self._tile_move_ready(tile):
                count += 1
        return count

    def _ground_build_allowed_fast(
        self,
        context: TurnContext,
        position: Position,
        tile: TileInfo | None,
        *,
        move_ready_adjacent_count: int | None = None,
    ) -> bool:
        if tile is None or tile.environment != Environment.EMPTY:
            return False
        if tile.building_type not in (None, EntityType.MARKER):
            return False
        if tile.building_type == EntityType.MARKER and tile.building_team not in (None, context.team):
            return False
        if (
            self.observed_first_delivery_round is None
            and context.titanium <= self._first_lane_reserve(context)
        ):
            if context.titanium < self._road_cost(context):
                return False
            if self.builder_state not in (BuilderStateV3.CLAIM_TITANIUM, BuilderStateV3.ROUTE_HOME_SAFE):
                ready_count = (
                    move_ready_adjacent_count
                    if move_ready_adjacent_count is not None
                    else self._move_ready_adjacent_count(context)
                )
                if ready_count > 1:
                    return False
        return True

    def _fast_step_move_feasible(
        self,
        context: TurnContext,
        position: Position,
        *,
        tile: TileInfo | None = None,
        move_ready_adjacent_count: int | None = None,
    ) -> bool:
        candidate_tile = context.tiles.get(position) if tile is None else tile
        if candidate_tile is None:
            return False
        if not self._tile_passable_for_route(candidate_tile):
            return False
        if candidate_tile.builder_bot_id not in (None, context.entity_id):
            return False
        if self._tile_move_ready(candidate_tile):
            return True
        return self._ground_build_allowed_fast(
            context,
            position,
            candidate_tile,
            move_ready_adjacent_count=move_ready_adjacent_count,
        )

    def _step_move_feasible(self, context: TurnContext, position: Position) -> bool:
        tile = context.tiles.get(position)
        if tile is None:
            return False
        if not self._tile_passable_for_route(tile):
            return False
        if tile.builder_bot_id not in (None, context.entity_id):
            return False
        if self._tile_move_ready(tile):
            return True
        return self._safe_ground_action(position, context) is not None

    def _choose_unmasked_adjacent(
        self,
        context: TurnContext,
        goal: Position,
        *,
        avoid_logistics: bool,
        avoid_recent_loop: bool = False,
    ) -> Position | None:
        logistics = self._logistics_positions(context) if avoid_logistics else set()
        recent_loop_positions = set(self.recent_positions[-12:]) if avoid_recent_loop else set()
        friendly_positions = self._friendly_builder_positions(context)
        move_ready_adjacent_count = None
        if (
            self.observed_first_delivery_round is None
            and self.builder_state not in (BuilderStateV3.CLAIM_TITANIUM, BuilderStateV3.ROUTE_HOME_SAFE)
        ):
            move_ready_adjacent_count = self._move_ready_adjacent_count(context)
        candidates: list[tuple[int, int, int, int, int, int, Position]] = []
        for idx, direction in enumerate(CARDINAL_DIRECTIONS):
            candidate = context.position.add(direction)
            if not self._in_bounds(context, candidate):
                continue
            tile = context.tiles.get(candidate)
            if tile is None:
                continue
            if not self._tile_passable_for_route(tile):
                continue
            if tile.builder_bot_id not in (None, context.entity_id):
                continue
            if not self._fast_step_move_feasible(
                context,
                candidate,
                tile=tile,
                move_ready_adjacent_count=move_ready_adjacent_count,
            ):
                continue
            loop_penalty = 1 if candidate in recent_loop_positions else 0
            candidates.append(
                (
                    1 if candidate in logistics else 0,
                    loop_penalty,
                    manhattan_distance(candidate, goal),
                    self._preferred_step_penalty(context, candidate),
                    *self._friendly_spacing_penalty(context, candidate, friendly_positions=friendly_positions),
                    idx,
                    candidate,
                )
            )
        if not candidates:
            return None
        return min(candidates)[-1]

    def _new_search_ticket(
        self,
        *,
        kind: SearchKind,
        origin: Position,
        goals: set[Position],
        waypoint: Position,
    ) -> SearchTicket:
        return SearchTicket(
            kind=kind,
            goals=set(goals),
            waypoint=waypoint,
            queue=deque([origin]),
            parents={origin: None},
            visited={origin},
            origin=origin,
        )

    def _ensure_search_ticket(
        self,
        context: TurnContext,
        *,
        kind: SearchKind,
        goals: set[Position],
        waypoint: Position,
    ) -> SearchTicket:
        existing = self.active_search_ticket
        if (
            existing is not None
            and existing.kind == kind
            and existing.goals == goals
            and existing.waypoint == waypoint
            and not existing.exhausted
        ):
            if context.position not in existing.visited:
                existing.visited.add(context.position)
                existing.parents[context.position] = None
                existing.queue.appendleft(context.position)
            return existing
        ticket = self._new_search_ticket(
            kind=kind,
            origin=context.position,
            goals=goals,
            waypoint=waypoint,
        )
        self.active_search_ticket = ticket
        self.micro_path = None
        return ticket

    def _reconstruct_ticket_path(self, ticket: SearchTicket, goal: Position) -> list[Position]:
        path: list[Position] = []
        current = goal
        while True:
            parent = ticket.parents.get(current)
            if parent is None:
                break
            path.append(current)
            current = parent
        path.reverse()
        return path

    def _is_adjacent_step(self, source: Position, target: Position) -> bool:
        dx = abs(source.x - target.x)
        dy = abs(source.y - target.y)
        return max(dx, dy) == 1

    def _ordered_search_directions(self, current: Position, waypoint: Position) -> tuple[Direction, ...]:
        directions = (*CARDINAL_DIRECTIONS, *DIAGONAL_DIRECTIONS)
        return tuple(
            sorted(
                directions,
                key=lambda direction: (
                    manhattan_distance(current.add(direction), waypoint),
                    0 if direction in CARDINAL_DIRECTIONS else 1,
                ),
            )
        )

    def _planner_expand_limit(self, context: TurnContext, ticket: SearchTicket) -> int:
        remaining_us = self._planner_remaining_us(context)
        expand_limit = self.config.planner_expand_default_budget
        # Start conservative, then spend extra search only when the turn still has
        # real headroom and the search is close enough to likely pay back quickly.
        if remaining_us >= self.config.planner_cpu_stop_us // 4:
            expand_limit = self.config.planner_expand_mid_budget
        close_to_waypoint = (
            manhattan_distance(context.position, ticket.waypoint) <= 8
            or len(ticket.queue) <= self.config.planner_expand_mid_budget
        )
        if remaining_us >= self.config.planner_cpu_stop_us // 2 and close_to_waypoint:
            expand_limit = self.config.planner_expand_budget
        return min(expand_limit, self.config.planner_expand_budget)

    def _resume_search_ticket(self, context: TurnContext) -> list[Position] | None:
        profile_start = perf_counter_ns() if self.profile_enabled else None
        ticket = self.active_search_ticket
        if ticket is None:
            self.last_planner_expansions = 0
            return None
        if context.position in ticket.goals:
            ticket.exhausted = True
            self.last_planner_expansions = 0
            return []
        remaining_us = self._planner_remaining_us(context)
        if remaining_us <= 0:
            self.last_planner_expansions = 0
            return None
        search_budget_cap_us = (
            self.config.planner_search_budget_cap_us
            if ticket.kind == SearchKind.ORE
            else self.config.planner_non_ore_search_budget_cap_us
        )
        remaining_us = min(remaining_us, search_budget_cap_us)
        if remaining_us <= 0:
            self.last_planner_expansions = 0
            return None
        expand_limit = self._planner_expand_limit(context, ticket)
        deadline_ns = perf_counter_ns() + (remaining_us * 1000)
        expansions = 0
        check_interval = max(1, self.config.planner_deadline_check_interval)
        time_exhausted = False
        while (
            ticket.queue
            and expansions < expand_limit
        ):
            if expansions and expansions % check_interval == 0 and perf_counter_ns() >= deadline_ns:
                break
            current = ticket.queue.popleft()
            expansions += 1
            if current in ticket.goals:
                ticket.expanded_total += expansions
                self.last_planner_expansions = expansions
                if profile_start is not None:
                    self._profile_record("resume_search_ticket", perf_counter_ns() - profile_start)
                return self._reconstruct_ticket_path(ticket, current)
            for direction in self._ordered_search_directions(current, ticket.waypoint):
                if perf_counter_ns() >= deadline_ns:
                    time_exhausted = True
                    break
                candidate = current.add(direction)
                if candidate in ticket.visited:
                    continue
                if not self._planner_passable(context, candidate):
                    continue
                ticket.visited.add(candidate)
                ticket.parents[candidate] = current
                ticket.queue.append(candidate)
            if time_exhausted:
                break

        ticket.expanded_total += expansions
        self.last_planner_expansions = expansions
        if not ticket.queue:
            ticket.exhausted = True
        if profile_start is not None:
            self._profile_record("resume_search_ticket", perf_counter_ns() - profile_start)
        return None

    def _materialize_micro_path(self, path: list[Position], waypoint: Position, kind: SearchKind, round_num: int) -> None:
        steps = list(path[: self.config.micro_path_len])
        self.micro_path = MicroPath(kind=kind, waypoint=waypoint, steps=steps, created_round=round_num)

    def _consume_micro_path_step(
        self,
        context: TurnContext,
        mask: ActionMask,
        *,
        kind: SearchKind,
        waypoint: Position,
    ) -> Position | None:
        micro = self.micro_path
        if micro is None or micro.kind != kind or micro.waypoint != waypoint:
            return None
        while micro.steps and micro.steps[0] == context.position:
            micro.steps.pop(0)
        if not micro.steps:
            self.micro_path = None
            return None
        next_position = micro.steps[0]
        if not self._is_adjacent_step(context.position, next_position):
            self.micro_path = None
            return None
        direction = context.position.direction_to(next_position)
        if direction not in mask.allowed_moves:
            self.micro_path = None
            return None
        micro.steps.pop(0)
        if not micro.steps:
            self.micro_path = None
        return next_position

    def _choose_masked_step(
        self,
        context: TurnContext,
        goal: Position,
        mask: ActionMask,
        *,
        frontier_mode: bool,
    ) -> Position | None:
        if not mask.allowed_moves:
            return None
        friendly_positions = self._friendly_builder_positions(context)
        return min(
            mask.allowed_moves.values(),
            key=lambda position: (
                manhattan_distance(position, goal),
                self._preferred_step_penalty(context, position),
                1 if frontier_mode and self._border_distance(context, position) <= 1 else 0,
                -unknown_neighbor_count(context, position) if frontier_mode else 0,
                *self._friendly_spacing_penalty(context, position, friendly_positions=friendly_positions),
                self._recent_visit_count(position),
                position.x,
                position.y,
            ),
        )

    def _choose_unknown_frontier_step(self, context: TurnContext, goal: Position) -> Position | None:
        candidates: list[tuple[int, int, int, int, int, int, Position]] = []
        friendly_positions = self._friendly_builder_positions(context)
        for idx, direction in enumerate(CARDINAL_DIRECTIONS):
            candidate = context.position.add(direction)
            if not self._in_bounds(context, candidate):
                continue
            if candidate in context.tiles or self._is_move_blacklisted(candidate):
                continue
            belief = self.belief_tiles.get(candidate)
            if belief is not None:
                if (
                    belief.last_seen_round >= context.round_num - self.config.ore_memory_ttl
                    and belief.environment == Environment.WALL
                ):
                    continue
                if belief.last_occupied_round >= context.round_num - self.config.occupancy_memory_ttl:
                    continue
            candidates.append(
                (
                    manhattan_distance(candidate, goal),
                    self._preferred_step_penalty(context, candidate),
                    1 if self._border_distance(context, candidate) <= 1 else 0,
                    *self._friendly_spacing_penalty(context, candidate, friendly_positions=friendly_positions),
                    self._recent_visit_count(candidate),
                    idx,
                    candidate,
                )
            )
        if not candidates:
            return None
        return min(candidates)[-1]

    def _preferred_step_penalty(self, context: TurnContext, position: Position) -> int:
        preferred = self.preferred_direction
        if preferred is None:
            return 0
        direction = context.position.direction_to(position)
        if direction == preferred:
            return 0
        if preferred == Direction.NORTH and direction in (Direction.NORTHWEST, Direction.NORTHEAST):
            return 0
        if preferred == Direction.SOUTH and direction in (Direction.SOUTHWEST, Direction.SOUTHEAST):
            return 0
        if preferred == Direction.EAST and direction in (Direction.NORTHEAST, Direction.SOUTHEAST):
            return 0
        if preferred == Direction.WEST and direction in (Direction.NORTHWEST, Direction.SOUTHWEST):
            return 0
        return 1

    def _move_with_planner(
        self,
        context: TurnContext,
        *,
        kind: SearchKind,
        goals: set[Position],
        waypoint: Position,
        note: str,
        frontier_mode: bool = False,
        marker_target: Position | None = None,
        marker_status: ClaimLaneStatus | None = None,
        lay_ground: bool = True,
    ) -> TurnPlan:
        profile_start = perf_counter_ns() if self.profile_enabled else None
        mask = self._build_action_mask(context, waypoint)
        search_min_remaining_us = self.config.planner_search_min_remaining_us
        if kind != SearchKind.ORE:
            search_min_remaining_us += 60

        step = self._consume_micro_path_step(context, mask, kind=kind, waypoint=waypoint)
        remaining_us = self._planner_remaining_us(context)
        search_entry_threshold = search_min_remaining_us + self.config.planner_search_entry_margin_us
        starvation_ore_search = kind == SearchKind.ORE and self._pre_delivery_starvation_mode(context)
        if step is None and (frontier_mode or starvation_ore_search) and unknown_neighbor_count(context, context.position) > 0:
            frontier_goal = waypoint if waypoint != context.position else (
                self._deep_frontier_target(context)
                if frontier_mode
                else self._exploration_focus(context)
            )
            step = self._choose_unknown_frontier_step(context, frontier_goal)
        if step is None:
            greedy_step = self._choose_masked_step(context, waypoint, mask, frontier_mode=frontier_mode)
            if (
                greedy_step is not None
                and not self._small_loop_risk()
                and manhattan_distance(greedy_step, waypoint) < manhattan_distance(context.position, waypoint)
            ):
                # Under the 2 ms budget, prefer an obvious improving move and
                # save resumable search for genuine obstacle / dead-end cases.
                step = greedy_step
            elif remaining_us > search_entry_threshold:
                self._ensure_search_ticket(context, kind=kind, goals=goals, waypoint=waypoint)
                path = self._resume_search_ticket(context)
                if path is not None:
                    if path and manhattan_distance(context.position, path[0]) != 1:
                        self.active_search_ticket = self._new_search_ticket(
                            kind=kind,
                            origin=context.position,
                            goals=goals,
                            waypoint=waypoint,
                        )
                        path = self._resume_search_ticket(context)
                    if path is not None:
                        self._materialize_micro_path(path, waypoint, kind, context.round_num)
                        step = self._consume_micro_path_step(context, mask, kind=kind, waypoint=waypoint)
        if step is None and (frontier_mode or starvation_ore_search):
            frontier_goal = waypoint if waypoint != context.position else (
                self._deep_frontier_target(context)
                if frontier_mode
                else self._exploration_focus(context)
            )
            step = self._choose_unknown_frontier_step(context, frontier_goal)
        if step is None:
            step = self._choose_masked_step(context, waypoint, mask, frontier_mode=frontier_mode)
            if step is None:
                step = self._choose_unmasked_adjacent(context, waypoint, avoid_logistics=False)
            if step is None:
                blocked_positions = self._logistics_positions(context) if frontier_mode else set()
                if self._small_loop_risk():
                    blocked_positions.update(self.recent_positions[-12:])
                bug_target = waypoint if waypoint != context.position else self._deep_frontier_target(context)
                step = choose_bug_escape_step(
                    context,
                    context.position,
                    bug_target,
                    recent_positions=self.recent_positions[-24:],
                    blocked_positions=blocked_positions,
                )
                if step is not None and not self._step_move_feasible(context, step):
                    step = None
            if step is None:
                plan = TurnPlan(
                    marker=self._claim_marker(context, marker_target, status=marker_status),
                    note=f"{note} hold",
                )
                if profile_start is not None:
                    self._profile_record("move_with_planner", perf_counter_ns() - profile_start)
                return plan
            ground = (
                self._safe_ground_action(step, context)
                if lay_ground and context.tiles.get(step) is not None
                else None
            )
            plan = TurnPlan(
                marker=self._claim_marker(context, marker_target, status=marker_status),
                action=ground,
                move=MoveDecision(context.position.direction_to(step)),
                note=f"{note} fallback",
            )
            plan = self._apply_diagonal_bridge(context, plan)
            if profile_start is not None:
                self._profile_record("move_with_planner", perf_counter_ns() - profile_start)
            return plan

        ground = (
            self._safe_ground_action(step, context)
            if lay_ground and context.tiles.get(step) is not None
            else None
        )
        plan = TurnPlan(
            marker=self._claim_marker(context, marker_target, status=marker_status),
            action=ground,
            move=MoveDecision(context.position.direction_to(step)),
            note=note,
        )
        plan = self._apply_diagonal_bridge(context, plan)
        if profile_start is not None:
            self._profile_record("move_with_planner", perf_counter_ns() - profile_start)
        return plan

    def _is_recent_healthy_artery(self, position: Position, context: TurnContext) -> bool:
        key = self._tile_key(position)
        seen_round = self.healthy_artery_tiles.get(key)
        if seen_round is None:
            return False
        return seen_round >= context.round_num - self.config.artery_memory_ttl

    def _update_congestion_streak(self, position: Position, context: TurnContext, active: bool) -> int:
        key = self._tile_key(position)
        last_round, streak = self.congestion_streaks.get(key, (-9999, 0))
        if not active:
            self.congestion_streaks[key] = (context.round_num, 0)
            return 0
        if last_round == context.round_num - 1:
            streak += 1
        else:
            streak = 1
        self.congestion_streaks[key] = (context.round_num, streak)
        return streak

    def _segment_tile_snapshot(
        self,
        context: TurnContext,
        position: Position,
    ) -> tuple[EntityType | None, Team | None, Environment | None, Direction | None, Position | None, bool]:
        tile = context.tiles.get(position)
        if tile is not None:
            direction = None
            bridge_target = None
            if tile.building_type in (EntityType.CONVEYOR, EntityType.BRIDGE) and tile.building_id is not None:
                entity = context.entities.get(tile.building_id)
                if entity is not None:
                    direction = entity.direction
                    bridge_target = entity.bridge_target
            return tile.building_type, tile.building_team, tile.environment, direction, bridge_target, True
        belief = self.belief_tiles.get(position)
        if belief is None:
            return None, None, None, None, None, False
        if belief.last_seen_round < context.round_num - self.config.route_memory_ttl:
            return None, None, None, None, None, False
        return belief.building_type, belief.building_team, belief.environment, belief.direction, belief.bridge_target, False

    def _pipeline_next_hop(self, context: TurnContext, position: Position) -> Position | None:
        tile = context.tiles.get(position)
        if tile is None or tile.building_team != context.team:
            return None
        if tile.building_type == EntityType.CORE:
            return position
        entity = context.entities.get(tile.building_id) if tile.building_id is not None else None
        if tile.building_type == EntityType.CONVEYOR:
            if entity is None or entity.direction is None:
                return None
            return position.add(entity.direction)
        if tile.building_type == EntityType.BRIDGE:
            if entity is None or entity.bridge_target is None:
                return None
            return entity.bridge_target
        return None

    def _belief_pipeline_next_hop(self, context: TurnContext, position: Position) -> Position | None:
        remembered = self.belief_tiles.get(position)
        if remembered is None:
            return None
        if remembered.last_seen_round < context.round_num - self.config.route_memory_ttl:
            return None
        if remembered.building_team != context.team:
            return None
        if remembered.building_type == EntityType.CORE:
            return position
        if remembered.building_type == EntityType.CONVEYOR:
            if remembered.direction is None:
                return None
            return position.add(remembered.direction)
        if remembered.building_type == EntityType.BRIDGE:
            return remembered.bridge_target
        return None

    def _best_coreward_direction(self, context: TurnContext, position: Position) -> Direction | None:
        target = self.anchor_position
        if target is None:
            core_positions = [
                tile.position
                for tile in context.tiles.values()
                if tile.building_type == EntityType.CORE and tile.building_team == context.team
            ]
            if core_positions:
                target = min(
                    core_positions,
                    key=lambda core_position: (
                        manhattan_distance(position, core_position),
                        core_position.x,
                        core_position.y,
                    ),
                )
        if target is None:
            return None
        current_distance = manhattan_distance(position, target)
        candidates: list[tuple[int, int, int, Direction]] = []
        for idx, direction in enumerate(CARDINAL_DIRECTIONS):
            candidate = position.add(direction)
            if not self._in_bounds(context, candidate):
                continue
            tile = context.tiles.get(candidate)
            if tile is not None:
                if not self._tile_passable_for_route(tile):
                    continue
                if tile.building_team not in (None, context.team):
                    continue
                route_bonus = 0
                if tile.building_type == EntityType.CORE:
                    route_bonus = -2
                elif tile.building_type in (EntityType.CONVEYOR, EntityType.BRIDGE) and tile.building_team == context.team:
                    # Do not route into a friendly conveyor unless its visible
                    # chain is already proven to sink into the core.
                    if self._trace_visible_pipeline(context, candidate):
                        route_bonus = -1
                    elif self.observed_first_delivery_round is None:
                        # Before first confirmed delivery, allow coreward
                        # bootstrap through unproven friendly logistics so we
                        # do not dead-end route recovery near congested lanes.
                        if manhattan_distance(candidate, target) >= current_distance:
                            continue
                        route_bonus = 1
                    else:
                        continue
            else:
                route_bonus = 0
            candidates.append(
                (
                    route_bonus,
                    manhattan_distance(candidate, target),
                    idx,
                    direction,
                )
            )
        if not candidates:
            return None
        return min(candidates)[3]

    def _direction_preserves_delivery_to_core(
        self,
        context: TurnContext,
        position: Position,
        direction: Direction,
    ) -> bool:
        output = position.add(direction)
        if not self._in_bounds(context, output):
            return False
        tile = context.tiles.get(output)
        if tile is not None:
            if tile.environment == Environment.WALL:
                return False
            if tile.environment in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                return False
            if tile.building_team not in (None, context.team):
                return False
            if tile.building_type == EntityType.CORE and tile.building_team == context.team:
                return True
            if tile.building_type in (EntityType.CONVEYOR, EntityType.BRIDGE) and tile.building_team == context.team:
                if self._trace_visible_pipeline(context, output):
                    return True
                if self.observed_first_delivery_round is None:
                    if self.anchor_position is None:
                        return True
                    return manhattan_distance(output, self.anchor_position) < manhattan_distance(position, self.anchor_position)
                return False
            if tile.building_type not in (None, EntityType.ROAD, EntityType.MARKER):
                return False
        if self.anchor_position is None:
            return True
        if self._is_recent_healthy_artery(output, context):
            return True
        return manhattan_distance(output, self.anchor_position) < manhattan_distance(position, self.anchor_position)

    def _allow_pre_delivery_route_detour(self, context: TurnContext, direction: Direction) -> bool:
        if self.observed_first_delivery_round is not None:
            return False
        if self.anchor_position is None:
            return False
        if self._small_loop_risk(window=20):
            return False
        current_distance = manhattan_distance(context.position, self.anchor_position)
        next_distance = manhattan_distance(context.position.add(direction), self.anchor_position)
        # Before first confirmed delivery, permit one-step neutral/slightly worse
        # detours so route builders can navigate around local chokepoints instead
        # of freezing and leaving disconnected harvesters.
        return next_distance <= current_distance + 1

    def _allow_pre_delivery_conveyor_rewrite(self, context: TurnContext, direction: Direction) -> bool:
        if self.observed_first_delivery_round is not None:
            return False
        if self.anchor_position is None:
            return False
        if self._small_loop_risk(window=20):
            return False
        return self._direction_preserves_delivery_to_core(context, context.position, direction)

    def _bridge_target_is_valid(
        self,
        context: TurnContext,
        *,
        site: Position,
        target: Position,
        avoid: Position | None,
    ) -> bool:
        if target == site:
            return False
        if avoid is not None and target == avoid:
            return False
        if not self._in_bounds(context, target):
            return False
        dx = target.x - site.x
        dy = target.y - site.y
        if dx * dx + dy * dy > 9:
            return False
        tile = context.tiles.get(target)
        if tile is None:
            return True
        if tile.environment in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
            return False
        if tile.builder_bot_id not in (None, context.entity_id):
            return False
        if tile.building_team not in (None, context.team):
            return False
        if tile.building_type in (
            EntityType.BARRIER,
            EntityType.GUNNER,
            EntityType.SENTINEL,
            EntityType.BREACH,
            EntityType.LAUNCHER,
            EntityType.HARVESTER,
            EntityType.FOUNDRY,
        ):
            return False
        return True

    def _choose_bridge_target(
        self,
        context: TurnContext,
        *,
        site: Position,
        avoid: Position | None = None,
    ) -> Position | None:
        coreward = self._best_coreward_direction(context, site)
        if coreward is not None:
            candidate = site.add(coreward)
            if self._bridge_target_is_valid(context, site=site, target=candidate, avoid=avoid):
                return candidate
        focus = self.anchor_position or self._map_center(context)
        candidates: list[tuple[int, int, int, int, Position]] = []
        for idx, direction in enumerate(CARDINAL_DIRECTIONS):
            candidate = site.add(direction)
            if not self._bridge_target_is_valid(context, site=site, target=candidate, avoid=avoid):
                continue
            candidates.append(
                (
                    manhattan_distance(candidate, focus),
                    idx,
                    candidate.x,
                    candidate.y,
                    candidate,
                )
            )
        if not candidates:
            return None
        return min(candidates)[4]

    def _classify_segment_from_export(
        self,
        context: TurnContext,
        export: Position,
    ) -> LaneHealthReport:
        # Only audit the locally visible or recently trusted segment. If the lane
        # disappears into fog without contradiction, leave it UNKNOWN instead of
        # overfitting a full-route story the acting builder cannot actually prove.
        anomalies: list[Position] = []
        repair_directions: dict[Position, Direction] = {}
        congested_tiles: list[Position] = []
        segment_tiles: list[Position] = []
        seen: set[Position] = set()

        current = export
        coherent_direction: Direction | None = None
        conflict_detected = False
        unknown_cutoff = False
        reached_healthy = False

        for _ in range(self.config.route_segment_limit):
            segment_tiles.append(current)
            if current in seen:
                anomalies.append(current)
                conflict_detected = True
                break
            seen.add(current)

            building_type, building_team, environment, direction, bridge_target, visible = self._segment_tile_snapshot(
                context, current
            )
            if building_type is None and building_team is None:
                repair_direction = self._best_coreward_direction(context, current)
                if repair_direction is not None:
                    anomalies.append(current)
                    repair_directions[current] = repair_direction
                    break
                if self._is_recent_healthy_artery(current, context):
                    reached_healthy = True
                    break
                unknown_cutoff = True
                break
            if building_team != context.team:
                anomalies.append(current)
                break
            if building_type == EntityType.CORE:
                reached_healthy = True
                break
            if building_type not in (EntityType.CONVEYOR, EntityType.BRIDGE):
                if building_type in (EntityType.ROAD, EntityType.MARKER):
                    repair_direction = self._best_coreward_direction(context, current)
                    if repair_direction is not None:
                        anomalies.append(current)
                        repair_directions[current] = repair_direction
                        break
                anomalies.append(current)
                break
            if building_type == EntityType.CONVEYOR and direction is None:
                anomalies.append(current)
                break
            if building_type == EntityType.BRIDGE and bridge_target is None:
                anomalies.append(current)
                break
            current_tile = context.tiles.get(current)
            current_entity = context.entities.get(current_tile.building_id) if (
                current_tile is not None
                and current_tile.building_id is not None
            ) else None
            if building_type in (
                EntityType.CONVEYOR,
                EntityType.SPLITTER,
                EntityType.ARMOURED_CONVEYOR,
            ):
                if current_entity is not None and current_entity.stored_resource is not None:
                    streak = self._update_congestion_streak(current, context, active=True)
                    if streak >= 3:
                        congested_tiles.append(current)

            if building_type == EntityType.CONVEYOR:
                if coherent_direction is None:
                    coherent_direction = direction
                elif OPPOSITE_DIRECTION.get(coherent_direction) == direction:
                    anomalies.append(current)
                    conflict_detected = True
                assert direction is not None
                output = current.add(direction)
                repair_directions[current] = direction
            else:
                output = bridge_target
                if output is not None:
                    to_output = current.direction_to(output)
                    if to_output in DIAGONAL_DIRECTIONS:
                        repair_directions[current] = to_output
            if not self._in_bounds(context, output):
                anomalies.append(current)
                break

            output_tile = context.tiles.get(output)
            if output_tile is not None:
                if output_tile.environment == Environment.WALL:
                    anomalies.append(current)
                if output_tile.environment in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                    anomalies.append(current)
                if output_tile.building_type is None:
                    anomalies.append(current)
                elif output_tile.building_team != context.team and output_tile.building_type is not None:
                    anomalies.append(current)
                elif (
                    output_tile.building_team == context.team
                    and output_tile.building_type
                    not in (EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.CORE, EntityType.ROAD, EntityType.MARKER)
                ):
                    anomalies.append(current)

                if output_tile.builder_bot_id not in (None, context.entity_id):
                    streak = self._update_congestion_streak(output, context, active=True)
                    if streak >= 3:
                        congested_tiles.append(output)
                else:
                    self._update_congestion_streak(output, context, active=False)

                if output_tile.building_type in (EntityType.CONVEYOR, EntityType.BRIDGE) and output_tile.building_id is not None:
                    output_entity = context.entities.get(output_tile.building_id)
                    if output_entity is not None and output_entity.stored_resource is not None:
                        streak = self._update_congestion_streak(output, context, active=True)
                        if streak >= 3:
                            congested_tiles.append(output)
                    next_hop = self._pipeline_next_hop(context, output)
                    if next_hop is not None and next_hop == current:
                        anomalies.append(output)
                        conflict_detected = True

            elif not self._is_recent_healthy_artery(output, context):
                remembered = self.belief_tiles.get(output)
                if remembered is None or remembered.last_seen_round < context.round_num - self.config.route_memory_ttl:
                    unknown_cutoff = True
                    break
                if remembered.building_team != context.team or remembered.building_type not in (
                    EntityType.CONVEYOR,
                    EntityType.BRIDGE,
                    EntityType.CORE,
                ):
                    anomalies.append(current)
                    break

            current = output

        anomaly_count = len({self._tile_key(position) for position in anomalies})
        has_congestion = bool(congested_tiles)

        if conflict_detected or anomaly_count >= 3:
            status = RouteHealth.UNSALVAGEABLE_LOCAL
        elif anomaly_count in (1, 2):
            status = RouteHealth.REPAIRABLE_FAULT
        elif has_congestion:
            status = RouteHealth.CONGESTED
        elif reached_healthy:
            status = RouteHealth.HEALTHY_LOCAL
        elif unknown_cutoff:
            status = RouteHealth.UNKNOWN
        else:
            status = RouteHealth.UNSALVAGEABLE_LOCAL

        return LaneHealthReport(
            ore_position=export,
            status=status,
            anomaly_tiles=anomalies,
            repair_directions=repair_directions,
            congested_tiles=congested_tiles,
            segment_tiles=segment_tiles,
        )

    def _classify_visible_titanium_lane(self, context: TurnContext, ore_position: Position) -> LaneHealthReport:
        exports = [
            ore_position.add(Direction.NORTH),
            ore_position.add(Direction.SOUTH),
            ore_position.add(Direction.EAST),
            ore_position.add(Direction.WEST),
        ]
        reports: list[LaneHealthReport] = []
        for export in exports:
            if not self._in_bounds(context, export):
                continue
            reports.append(self._classify_segment_from_export(context, export))
        if not reports:
            return LaneHealthReport(ore_position=ore_position, status=RouteHealth.UNKNOWN)

        statuses = {report.status for report in reports}
        if RouteHealth.HEALTHY_LOCAL in statuses:
            status = RouteHealth.HEALTHY_LOCAL
        elif RouteHealth.CONGESTED in statuses:
            status = RouteHealth.CONGESTED
        elif RouteHealth.REPAIRABLE_FAULT in statuses:
            status = RouteHealth.REPAIRABLE_FAULT
        elif RouteHealth.UNSALVAGEABLE_LOCAL in statuses:
            status = RouteHealth.UNSALVAGEABLE_LOCAL
        else:
            status = RouteHealth.UNKNOWN

        anomaly_tiles: list[Position] = []
        congested_tiles: list[Position] = []
        repair_directions: dict[Position, Direction] = {}
        segment_tiles: list[Position] = []
        for report in reports:
            anomaly_tiles.extend(report.anomaly_tiles)
            congested_tiles.extend(report.congested_tiles)
            repair_directions.update(report.repair_directions)
            segment_tiles.extend(report.segment_tiles)

        lane_report = LaneHealthReport(
            ore_position=ore_position,
            status=status,
            anomaly_tiles=anomaly_tiles,
            repair_directions=repair_directions,
            congested_tiles=congested_tiles,
            segment_tiles=segment_tiles,
        )
        if status == RouteHealth.HEALTHY_LOCAL:
            for tile in lane_report.segment_tiles:
                self.healthy_artery_tiles[self._tile_key(tile)] = context.round_num
            memory = self.ore_memory.get(ore_position)
            if memory is not None:
                memory.last_healthy_round = context.round_num
        elif status in (RouteHealth.REPAIRABLE_FAULT, RouteHealth.UNSALVAGEABLE_LOCAL):
            memory = self.ore_memory.get(ore_position)
            if memory is not None:
                memory.last_healthy_round = -1
        return lane_report

    def _record_lane_congestion_observations(self, context: TurnContext, reports: list[LaneHealthReport]) -> None:
        for report in reports:
            key = self._tile_key(report.ore_position)
            previous = self.lane_congestion_observations.get(key)
            streak = 0
            if report.status == RouteHealth.CONGESTED:
                if previous is not None and previous[0] >= context.round_num - self.config.throughput_scan_freshness_rounds:
                    streak = previous[1] + 1
                else:
                    streak = 1
            self.lane_congestion_observations[key] = (context.round_num, streak)

    def _ore_congestion_observation_count(self, context: TurnContext, ore_position: Position) -> int:
        observed = self.lane_congestion_observations.get(self._tile_key(ore_position))
        if observed is None:
            return 0
        observed_round, observed_count = observed
        if observed_round < context.round_num - self.config.throughput_scan_freshness_rounds:
            return 0
        return observed_count

    def _throughput_saturated(self, context: TurnContext, reports: list[LaneHealthReport]) -> bool:
        congested_reports = [report for report in reports if report.status == RouteHealth.CONGESTED]
        if not congested_reports:
            return False
        persistent_congestion = any(
            self._ore_congestion_observation_count(context, report.ore_position)
            >= self.config.throughput_congestion_observations
            for report in congested_reports
        )
        if not persistent_congestion:
            return False
        sample_window = max(6, self.config.flow_window // 2)
        average_inflow = (
            sum(self.net_titanium_inflow_window) / float(len(self.net_titanium_inflow_window))
            if self.net_titanium_inflow_window
            else 0.0
        )
        inbound_rounds = sum(1 for observed in self.inbound_logistics_window if observed)
        low_inflow = (
            len(self.net_titanium_inflow_window) >= sample_window
            and average_inflow < float(self.config.flow_avg_inflow_threshold)
        )
        weak_inbound = (
            len(self.inbound_logistics_window) >= sample_window
            and inbound_rounds < self.config.flow_inbound_min_rounds
        )
        return low_inflow or weak_inbound

    def _scan_visible_titanium_route_health(self, context: TurnContext) -> list[LaneHealthReport]:
        profile_start = perf_counter_ns() if self.profile_enabled else None
        reports: list[LaneHealthReport] = []
        candidate_ores: list[Position] = []
        for ore_position in context.visible_ore_tiles:
            if manhattan_distance(context.position, ore_position) > self.config.route_health_local_radius:
                continue
            tile = context.tiles.get(ore_position)
            if tile is None or tile.environment != Environment.ORE_TITANIUM:
                continue
            if tile.building_type != EntityType.HARVESTER or tile.building_team != context.team:
                continue
            candidate_ores.append(ore_position)
        candidate_ores.sort(
            key=lambda position: (
                manhattan_distance(context.position, position),
                position.x,
                position.y,
            )
        )
        for ore_position in candidate_ores[: self.config.route_health_max_reports]:
            reports.append(self._classify_visible_titanium_lane(context, ore_position))
        self._record_lane_congestion_observations(context, reports)
        if profile_start is not None:
            self._profile_record("scan_route_health", perf_counter_ns() - profile_start)
        return reports

    def _pick_repairable_lane(self, context: TurnContext, reports: list[LaneHealthReport]) -> LaneHealthReport | None:
        candidates: list[LaneHealthReport] = []
        for report in reports:
            if report.status not in (RouteHealth.REPAIRABLE_FAULT, RouteHealth.UNSALVAGEABLE_LOCAL):
                continue
            if not report.anomaly_tiles:
                continue
            # Unsalvageable local classification still often contains a
            # deterministic local rewrite (e.g., local cycle/conflict) and
            # should not be ignored when no healthy lane exists.
            if report.status == RouteHealth.UNSALVAGEABLE_LOCAL and not report.repair_directions:
                continue
            owner = self._repair_owner_for_ore(context, report.ore_position)
            if owner is not None and owner != context.entity_id:
                continue
            candidates.append(report)
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda report: (
                0 if self._repair_owner_for_ore(context, report.ore_position) == context.entity_id else 1,
                0 if report.status == RouteHealth.REPAIRABLE_FAULT else 1,
                min(manhattan_distance(context.position, tile) for tile in report.anomaly_tiles),
                report.ore_position.x,
                report.ore_position.y,
            ),
        )

    def _pick_congested_lane(self, context: TurnContext, reports: list[LaneHealthReport]) -> LaneHealthReport | None:
        candidates: list[LaneHealthReport] = []
        for report in reports:
            if report.status != RouteHealth.CONGESTED or not report.congested_tiles:
                continue
            owner = self._repair_owner_for_ore(context, report.ore_position)
            if owner is not None and owner != context.entity_id:
                continue
            if owner is None:
                memory = self.ore_memory.get(report.ore_position)
                if (
                    memory is None
                    or not memory.has_friendly_harvester
                    or memory.last_harvester_round < context.round_num - 40
                ):
                    # Decongestion is lane-owner work; avoid siphoning builders
                    # into foreign/unknown lanes without local ownership signal.
                    continue
            candidates.append(report)
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda report: (
                0 if self._repair_owner_for_ore(context, report.ore_position) == context.entity_id else 1,
                min(manhattan_distance(context.position, tile) for tile in report.congested_tiles),
                report.ore_position.x,
                report.ore_position.y,
            ),
        )

    def _repair_lane_plan(self, context: TurnContext, report: LaneHealthReport) -> TurnPlan:
        report_status = getattr(report, "status", RouteHealth.REPAIRABLE_FAULT)
        target_candidates = list(report.anomaly_tiles)
        if (
            report_status == RouteHealth.UNSALVAGEABLE_LOCAL
            or self._pre_delivery_starvation_mode(context)
        ):
            actionable = [
                position for position in report.anomaly_tiles if position in report.repair_directions
            ]
            if actionable:
                target_candidates = actionable
        target = min(
            target_candidates,
            key=lambda position: (manhattan_distance(context.position, position), position.x, position.y),
        )
        direction = report.repair_directions.get(target)
        if context.position == target:
            if direction is None:
                direction = self._best_coreward_direction(context, context.position)
            tile = context.tiles.get(context.position)
            if (
                tile is not None
                and tile.building_type == EntityType.CONVEYOR
                and tile.building_team == context.team
            ):
                if direction is not None and self._allow_pre_delivery_conveyor_rewrite(context, direction):
                    if context.titanium < self._conveyor_cost(context):
                        return TurnPlan(
                            marker=self._claim_marker(context, report.ore_position, status=ClaimLaneStatus.REPAIR),
                            note="policy_fsm_v3 repair wait titanium",
                        )
                    allowed, _ = self._build_allowed_candidates(
                        context,
                        [context.position],
                        kind=BuildKind.CONVEYOR,
                        direction=direction,
                        replace_existing=True,
                        allow_protected_rewrite=True,
                    )
                    if allowed:
                        return TurnPlan(
                            marker=self._claim_marker(context, report.ore_position, status=ClaimLaneStatus.REPAIR),
                            action=BuildDecision(
                                kind=BuildKind.CONVEYOR,
                                position=context.position,
                                direction=direction,
                                replace_existing=True,
                            ),
                            note="policy_fsm_v3 repair rewrite conveyor",
                        )
                # Preserve proven healthy lanes by refusing to rewrite sink-valid
                # conveyors during repair mode.
                self._mark_splice_blocked(context.position, context)
                escape = self._escape_from_logistics(context, note="policy_fsm_v3 repair preserve conveyor")
                if escape is not None:
                    escape.marker = self._claim_marker(context, report.ore_position, status=ClaimLaneStatus.REPAIR)
                    return escape
                return TurnPlan(
                    marker=self._claim_marker(context, report.ore_position, status=ClaimLaneStatus.REPAIR),
                    note="policy_fsm_v3 repair preserve hold",
                )
            replace_existing = tile is not None and tile.building_type in (EntityType.ROAD, EntityType.MARKER, EntityType.CONVEYOR)
            if direction is not None:
                if not self._direction_preserves_delivery_to_core(context, context.position, direction):
                    direction = None
            if direction is not None:
                if context.titanium < self._conveyor_cost(context):
                    escape = self._escape_from_logistics(context, note="policy_fsm_v3 repair wait titanium")
                    if escape is not None:
                        escape.marker = self._claim_marker(context, report.ore_position, status=ClaimLaneStatus.REPAIR)
                        return escape
                    return TurnPlan(
                        marker=self._claim_marker(context, report.ore_position, status=ClaimLaneStatus.REPAIR),
                        note="policy_fsm_v3 repair hold",
                    )
                allowed, _ = self._build_allowed_candidates(
                    context,
                    [context.position],
                    kind=BuildKind.CONVEYOR,
                    direction=direction,
                    replace_existing=replace_existing,
                )
                if allowed:
                    return TurnPlan(
                        marker=self._claim_marker(context, report.ore_position, status=ClaimLaneStatus.REPAIR),
                        action=BuildDecision(
                            kind=BuildKind.CONVEYOR,
                            position=context.position,
                            direction=direction,
                            replace_existing=replace_existing,
                        ),
                        note="policy_fsm_v3 repair fault",
                    )
            escape = self._escape_from_logistics(context, note="policy_fsm_v3 repair fallback escape")
            if escape is not None:
                escape.marker = self._claim_marker(context, report.ore_position, status=ClaimLaneStatus.REPAIR)
                return escape
            return TurnPlan(
                marker=self._claim_marker(context, report.ore_position, status=ClaimLaneStatus.REPAIR),
                note="policy_fsm_v3 repair hold",
            )

        goals = {target}
        self.builder_state = BuilderStateV3.CLAIM_TITANIUM
        return self._move_with_planner(
            context,
            kind=SearchKind.ESCAPE,
            goals=goals,
            waypoint=target,
            note="policy_fsm_v3 move to repair",
            frontier_mode=False,
            marker_target=report.ore_position,
            marker_status=ClaimLaneStatus.REPAIR,
        )

    def _decongest_lane_plan(self, context: TurnContext, report: LaneHealthReport) -> TurnPlan:
        target = min(
            report.congested_tiles,
            key=lambda position: (manhattan_distance(context.position, position), position.x, position.y),
        )
        if context.position == target:
            escape = self._escape_from_logistics(context, note="policy_fsm_v3 decongest vacate")
            if escape is not None:
                escape.marker = self._claim_marker(context, report.ore_position, status=ClaimLaneStatus.REPAIR)
                return escape
            return TurnPlan(
                marker=self._claim_marker(context, report.ore_position, status=ClaimLaneStatus.REPAIR),
                note="policy_fsm_v3 decongest hold",
            )
        return self._move_with_planner(
            context,
            kind=SearchKind.ESCAPE,
            goals={target},
            waypoint=target,
            note="policy_fsm_v3 move to decongest",
            frontier_mode=False,
            marker_target=report.ore_position,
            marker_status=ClaimLaneStatus.REPAIR,
        )

    def _expand_congested_lane_plan(self, context: TurnContext, report: LaneHealthReport) -> TurnPlan | None:
        ore_position = report.ore_position
        owner = self._repair_owner_for_ore(context, ore_position)
        if owner is not None and owner != context.entity_id:
            return None
        goals = {
            goal
            for goal in self._ore_adjacent_positions(context, ore_position)
            if not self._goal_is_hard_blocked(context, goal)
        }
        if not goals:
            return None
        if context.position not in goals:
            self.builder_state = BuilderStateV3.CLAIM_TITANIUM
            return self._move_with_planner(
                context,
                kind=SearchKind.ESCAPE,
                goals=goals,
                waypoint=self._best_lane_goal(context, goals),
                note="policy_fsm_v3 move to congested lane expansion",
                frontier_mode=False,
                marker_target=ore_position,
                marker_status=ClaimLaneStatus.REPAIR,
            )

        self.current_lane_target = ore_position
        self._mark_lane_commit(context, ore_position)
        self.current_lane_goal = context.position
        self.pending_harvester = None
        self._reset_goal_progress()
        self.route_last_position = None
        self.route_stall_counter = 0
        self.route_wait_target = None
        self.route_wait_counter = 0
        self.route_resume_target = None
        self.route_resume_failures = 0
        self.route_pending_bridge = None
        self.route_history = list(self.trail)
        if self.route_history and self.route_history[-1] != context.position:
            self.route_history.append(context.position)
        self.route_cursor = len(self.route_history) - 1 if self.route_history else None
        self.builder_state = BuilderStateV3.ROUTE_HOME_SAFE
        self.mode = "return_route"
        plan = self._safe_route_plan(context)
        if plan.marker is None:
            plan.marker = self._claim_marker(context, ore_position, status=ClaimLaneStatus.ROUTING)
        return plan

    def _ore_adjacent_positions(self, context: TurnContext, ore_position: Position) -> set[Position]:
        self._reset_turn_caches(context)
        key = self._tile_key(ore_position)
        cached = self.turn_ore_goals_cache.get(key)
        if cached is not None:
            return cached
        goals = (
            ore_position.add(Direction.NORTH),
            ore_position.add(Direction.SOUTH),
            ore_position.add(Direction.EAST),
            ore_position.add(Direction.WEST),
        )
        in_bounds_goals = {position for position in goals if self._in_bounds(context, position)}
        self.turn_ore_goals_cache[key] = in_bounds_goals
        return in_bounds_goals

    def _route_has_capacity_for_goals(self, context: TurnContext, goals: set[Position]) -> bool:
        if not goals:
            return False
        slots = 0
        occupied = 0
        for goal in sorted(goals, key=lambda position: (position.x, position.y)):
            tile = context.tiles.get(goal)
            if tile is None:
                # Keep unseen goal tiles eligible so starvation-mode ore scoring
                # can prefer unseen cluster members over visible local traps.
                slots += 1
                continue
            if self._tile_passable_for_route(tile):
                slots += 1
            if tile.builder_bot_id not in (None, context.entity_id):
                occupied += 1
        return slots > 0 and occupied < slots

    def _route_has_capacity(self, context: TurnContext, ore_position: Position) -> bool:
        goals = self._ore_adjacent_positions(context, ore_position)
        return self._route_has_capacity_for_goals(context, goals)

    def _best_lane_goal(self, context: TurnContext, goals: set[Position]) -> Position:
        if not goals:
            return context.position
        viable_goals = {
            goal
            for goal in goals
            if not self._goal_is_hard_blocked(context, goal)
        }
        if not viable_goals:
            viable_goals = set(goals)
        if context.position in viable_goals:
            return context.position
        path = find_path_to_visible_goal(
            context,
            context.position,
            viable_goals,
            max_nodes=min(96, self.config.ore_path_max_nodes),
        )
        if path:
            return path[-1]
        return min(
            viable_goals,
            key=lambda goal: (
                manhattan_distance(context.position, goal),
                goal.x,
                goal.y,
            ),
        )

    def _goal_is_hard_blocked(self, context: TurnContext, goal: Position) -> bool:
        blocked_buildings = {
            EntityType.BARRIER,
            EntityType.GUNNER,
            EntityType.SENTINEL,
            EntityType.BREACH,
            EntityType.LAUNCHER,
            EntityType.HARVESTER,
            EntityType.FOUNDRY,
        }
        tile = context.tiles.get(goal)
        if tile is not None:
            if tile.environment == Environment.WALL:
                return True
            if tile.environment in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                return tile.building_type != EntityType.CORE
            return tile.building_type in blocked_buildings
        belief = self.belief_tiles.get(goal)
        if belief is None or belief.last_seen_round < context.round_num - self.config.ore_memory_ttl:
            return False
        if belief.environment == Environment.WALL:
            return True
        if belief.environment in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
            return belief.building_type != EntityType.CORE
        return belief.building_type in blocked_buildings

    def _ore_has_viable_goal(self, context: TurnContext, ore_position: Position) -> bool:
        goals = self._ore_adjacent_positions(context, ore_position)
        if not goals:
            return False
        return any(not self._goal_is_hard_blocked(context, goal) for goal in goals)

    def _ore_has_reachable_goal(self, context: TurnContext, ore_position: Position) -> bool:
        if not self._ore_has_viable_goal(context, ore_position):
            return False
        goals = self._ore_adjacent_positions(context, ore_position)
        if context.position in goals:
            return True
        path = find_path_to_visible_goal(context, context.position, goals, max_nodes=self.config.ore_path_max_nodes)
        return bool(path)

    def _ore_path_length(self, context: TurnContext, ore_position: Position) -> int | None:
        self._reset_turn_caches(context)
        key = self._tile_key(ore_position)
        if key in self.turn_ore_path_cache:
            return self.turn_ore_path_cache[key]
        goals = self._ore_adjacent_positions(context, ore_position)
        if not goals:
            self.turn_ore_path_cache[key] = None
            return None
        if context.position in goals:
            self.turn_ore_path_cache[key] = 0
            return 0
        if self.turn_ore_path_queries >= self.config.ore_path_query_limit:
            return None
        self.turn_ore_path_queries += 1
        bfs_start = perf_counter_ns() if self.profile_enabled else None
        path = find_path_to_visible_goal(context, context.position, goals, max_nodes=self.config.ore_path_max_nodes)
        if bfs_start is not None:
            self._profile_record("ore_path_bfs", perf_counter_ns() - bfs_start)
        if not path:
            self.turn_ore_path_cache[key] = None
            return None
        result = len(path)
        self.turn_ore_path_cache[key] = result
        return result

    def _ore_has_observed_goal(self, context: TurnContext, ore_position: Position) -> bool:
        return self._ore_has_viable_goal(context, ore_position)

    def _ore_target_score(
        self,
        context: TurnContext,
        cluster_size: int,
        memory: OreMemory,
        goals: set[Position] | None = None,
    ) -> tuple[int, int, int, int, int] | None:
        candidate_goals = goals if goals is not None else self._ore_adjacent_positions(context, memory.position)
        if not candidate_goals:
            return None
        if not any(not self._goal_is_hard_blocked(context, goal) for goal in candidate_goals):
            return None
        path_len = self._ore_path_length(context, memory.position)
        if path_len is None:
            estimated_len = min(manhattan_distance(context.position, goal) for goal in candidate_goals) + 6
            if memory.position in context.tiles:
                # In starvation mode, keep distant unseen candidates viable so
                # builders do not repeatedly lock to visible trap ores.
                if not self._pre_delivery_starvation_mode(context):
                    return None
                path_len = estimated_len + 48
            else:
                path_len = estimated_len
        return (
            path_len,
            -cluster_size,
            -(memory.last_seen_round),
            memory.position.x,
            memory.position.y,
        )

    def _mark_visible_unreachable_ores(self, context: TurnContext) -> None:
        profile_start = perf_counter_ns() if self.profile_enabled else None
        if not context.visible_ore_tiles:
            if profile_start is not None:
                self._profile_record("mark_visible_unreachable_ores", perf_counter_ns() - profile_start)
            return
        for ore_position in sorted(
            context.visible_ore_tiles,
            key=lambda position: (position.x, position.y),
        )[: self.config.visible_ore_hard_limit]:
            tile = context.tiles.get(ore_position)
            if tile is None or tile.environment != Environment.ORE_TITANIUM:
                continue
            if tile.building_type == EntityType.HARVESTER and tile.building_team == context.team:
                continue
            if self._ore_has_viable_goal(context, ore_position):
                continue
            self._mark_lane_failed(ore_position, context)
        if profile_start is not None:
            self._profile_record("mark_visible_unreachable_ores", perf_counter_ns() - profile_start)

    def _preferred_ore_focus(self, context: TurnContext) -> Position:
        if self.current_lane_target is not None and not self._lane_failed(self.current_lane_target):
            return self.current_lane_target
        for cluster in self.ore_clusters:
            viable_members = [ore for ore in cluster.members if not self._lane_failed(ore)]
            if viable_members:
                return cluster.centroid
        return self._map_center(context)

    def _drop_unreachable_visible_lane_target(self, context: TurnContext) -> None:
        profile_start = perf_counter_ns() if self.profile_enabled else None
        target = self.current_lane_target
        if target is None or target not in context.tiles:
            if profile_start is not None:
                self._profile_record("drop_unreachable_visible_lane_target", perf_counter_ns() - profile_start)
            return
        if self._ore_has_viable_goal(context, target):
            if profile_start is not None:
                self._profile_record("drop_unreachable_visible_lane_target", perf_counter_ns() - profile_start)
            return
        self._mark_lane_failed(target, context)
        self.current_lane_target = None
        self.current_lane_started_round = -1
        self.current_lane_goal = None
        self.pending_harvester = None
        self._reset_goal_progress()
        if profile_start is not None:
            self._profile_record("drop_unreachable_visible_lane_target", perf_counter_ns() - profile_start)

    def _select_titanium_cluster_target(
        self,
        context: TurnContext,
        *,
        allow_claimed_contest: bool = False,
    ) -> tuple[Position | None, set[Position]]:
        profile_start = perf_counter_ns() if self.profile_enabled else None
        prefilter_limit = max(self.config.ore_candidate_eval_limit, self.config.ore_prefilter_limit)
        starvation_mode = self._pre_delivery_starvation_mode(context)
        cheap_candidates: list[tuple[tuple[int, int, int, int, int, int], Position, set[Position], OreMemory, int]] = []
        scanned_ores = 0

        def _record_and_return(target: Position | None, goals: set[Position]) -> tuple[Position | None, set[Position]]:
            if profile_start is not None:
                self._profile_record("select_titanium_target", perf_counter_ns() - profile_start)
            return target, goals

        def _worst_candidate_index() -> int:
            worst_index = 0
            worst_key = cheap_candidates[0][0]
            for idx in range(1, len(cheap_candidates)):
                key = cheap_candidates[idx][0]
                if key > worst_key:
                    worst_key = key
                    worst_index = idx
            return worst_index

        for cluster in self.ore_clusters:
            for ore_position in cluster.members:
                scanned_ores += 1
                if (
                    scanned_ores % 8 == 0
                    and cheap_candidates
                    and self._planner_remaining_us(context) <= self.config.ore_scoring_min_remaining_us
                ):
                    break
                if self._lane_failed(ore_position):
                    continue
                claim_blocks = self._lane_claim_blocks_target(context, ore_position)
                if claim_blocks:
                    if not allow_claimed_contest:
                        continue
                    claim = self._visible_lane_claim(context.tiles.get(ore_position), context)
                    if claim is None:
                        continue
                    owner_id, status = claim
                    if owner_id != context.entity_id and status not in (
                        ClaimLaneStatus.CLAIMED,
                        ClaimLaneStatus.ROUTING,
                    ):
                        continue
                memory = self.ore_memory.get(ore_position)
                if memory is None:
                    continue
                if memory.has_friendly_harvester and memory.last_harvester_round >= context.round_num - 40:
                    continue
                goals = self._ore_adjacent_positions(context, ore_position)
                if not goals:
                    continue
                if not self._route_has_capacity_for_goals(context, goals):
                    continue
                visibility_bias = 0 if ore_position in context.tiles else 1
                if starvation_mode:
                    # Avoid over-prioritising currently visible ores before first
                    # income, which can trap builders on bad local pockets.
                    visibility_bias = 0
                candidate = (
                    (
                        visibility_bias,
                        manhattan_distance(context.position, ore_position),
                        -len(cluster.members),
                        -(memory.last_seen_round),
                        ore_position.x,
                        ore_position.y,
                    ),
                    ore_position,
                    goals,
                    memory,
                    len(cluster.members),
                )
                if len(cheap_candidates) < prefilter_limit:
                    cheap_candidates.append(candidate)
                    continue
                worst_idx = _worst_candidate_index()
                if candidate[0] < cheap_candidates[worst_idx][0]:
                    cheap_candidates[worst_idx] = candidate
            else:
                continue
            break

        if not cheap_candidates:
            return _record_and_return(None, set())
        cheap_candidates.sort(key=lambda item: item[0])
        if self._planner_remaining_us(context) <= self.config.ore_scoring_min_remaining_us:
            _, ore_position, goals, _memory, _cluster_size = cheap_candidates[0]
            return _record_and_return(ore_position, goals)

        scored_candidates: list[tuple[tuple[int, int, int, int, int], Position, set[Position]]] = []
        eval_limit = self.config.ore_candidate_eval_limit
        if starvation_mode:
            eval_limit = min(len(cheap_candidates), max(eval_limit, 6))
        for _, ore_position, goals, memory, cluster_size in cheap_candidates[:eval_limit]:
            if self._planner_remaining_us(context) <= self.config.ore_scoring_min_remaining_us:
                break
            score = self._ore_target_score(context, cluster_size, memory, goals)
            if score is None:
                continue
            scored_candidates.append((score, ore_position, goals))

        if scored_candidates:
            scored_candidates.sort(key=lambda item: item[0])
            _, ore_position, goals = scored_candidates[0]
            return _record_and_return(ore_position, goals)

        _, ore_position, goals, _memory, _cluster_size = cheap_candidates[0]
        return _record_and_return(ore_position, goals)

    def _has_recent_friendly_titanium_harvester(self, context: TurnContext) -> bool:
        horizon = max(40, self.config.flow_window)
        return any(
            memory.environment == Environment.ORE_TITANIUM
            and memory.has_friendly_harvester
            and memory.last_harvester_round >= context.round_num - horizon
            for memory in self.ore_memory.values()
        )

    def _pre_delivery_starvation_mode(self, context: TurnContext) -> bool:
        if self.observed_first_delivery_round is not None:
            return False
        if context.round_num < 80:
            return False
        if self._has_visible_team_titanium_harvester(context):
            return False
        if not self._has_recent_friendly_titanium_harvester(context):
            return bool(self.ore_memory) or bool(context.visible_ore_tiles)
        return False

    def _lane_target_goals_if_viable(self, context: TurnContext, ore_position: Position) -> set[Position] | None:
        if self._lane_failed(ore_position):
            return None
        if self._lane_claim_blocks_target(context, ore_position):
            return None
        memory = self.ore_memory.get(ore_position)
        if memory is None:
            return None
        if memory.has_friendly_harvester and memory.last_harvester_round >= context.round_num - 40:
            return None
        goals = self._ore_adjacent_positions(context, ore_position)
        if not goals:
            return None
        if not any(not self._goal_is_hard_blocked(context, goal) for goal in goals):
            return None
        if ore_position in context.tiles and self._pre_delivery_starvation_mode(context):
            if self._ore_path_length(context, ore_position) is None:
                return None
        if not self._route_has_capacity_for_goals(context, goals):
            return None
        return goals

    def _lane_target_viable(self, context: TurnContext, ore_position: Position) -> bool:
        return self._lane_target_goals_if_viable(context, ore_position) is not None

    def _has_visible_team_titanium_harvester(self, context: TurnContext) -> bool:
        for ore_position in context.visible_ore_tiles:
            tile = context.tiles.get(ore_position)
            if (
                tile is not None
                and tile.environment == Environment.ORE_TITANIUM
                and tile.building_type == EntityType.HARVESTER
                and tile.building_team == context.team
            ):
                return True
        return False

    def _continue_cached_lane_plan(self, context: TurnContext) -> TurnPlan | None:
        if (
            self.builder_state != BuilderStateV3.CLAIM_TITANIUM
            or self.current_lane_target is None
            or self.current_lane_goal is None
            or self.pending_harvester is not None
        ):
            return None
        tile = context.tiles.get(self.current_lane_target)
        if (
            tile is not None
            and tile.building_type == EntityType.HARVESTER
            and tile.building_team == context.team
        ):
            self.current_lane_target = None
            self.current_lane_started_round = -1
            self.current_lane_goal = None
            return None
        if context.round_num - self.last_lane_viability_round >= self.config.lane_viability_check_interval:
            self.last_lane_viability_round = context.round_num
            if not self._lane_target_viable(context, self.current_lane_target):
                self.current_lane_target = None
                self.current_lane_started_round = -1
                self.current_lane_goal = None
                self.pending_harvester = None
                self._reset_goal_progress()
                return None
        goals = self._ore_adjacent_positions(context, self.current_lane_target)
        if not goals or not self._ore_has_viable_goal(context, self.current_lane_target):
            return None
        self.current_lane_goal = self._best_lane_goal(context, goals)
        if context.position in goals:
            build_plan = self._build_harvester_if_adjacent(context, self.current_lane_target)
            if build_plan is not None:
                return build_plan
        return self._move_with_planner(
            context,
            kind=SearchKind.ORE,
            goals=goals,
            waypoint=self.current_lane_goal,
            note="policy_fsm_v3 move to titanium",
            frontier_mode=False,
            marker_target=self.current_lane_target,
        )

    def _continue_cached_frontier_plan(self, context: TurnContext) -> TurnPlan | None:
        micro = self.micro_path
        if (
            micro is None
            or micro.kind != SearchKind.FRONTIER
            or self.current_lane_target is not None
            or any(
                (
                    (tile := context.tiles.get(ore_position)) is not None
                    and tile.environment == Environment.ORE_TITANIUM
                    and tile.building_type != EntityType.HARVESTER
                )
                for ore_position in context.visible_ore_tiles
            )
        ):
            return None
        self._enter_patrol(context)
        return self._move_with_planner(
            context,
            kind=SearchKind.FRONTIER,
            goals={micro.waypoint},
            waypoint=micro.waypoint,
            note=f"policy_fsm_v3 patrol {self._patrol_mode(context).name.lower()}",
            frontier_mode=True,
            marker_target=None,
            lay_ground=False,
        )

    def _active_titanium_target(self, context: TurnContext) -> tuple[Position | None, set[Position]]:
        if self.current_lane_target is not None:
            goals = self._lane_target_goals_if_viable(context, self.current_lane_target)
            if goals is not None:
                return self.current_lane_target, goals
        target, goals = self._select_titanium_cluster_target(context)
        if target is not None:
            return target, goals
        if self._has_recent_friendly_titanium_harvester(context) and self._economy_bootstrapped(context):
            return None, set()
        # Avoid economic starvation when opponents aggressively pre-claim every
        # visible lane: if we have no live titanium lane, allow contesting
        # foreign CLAIMED/ROUTING markers as a fallback.
        return self._select_titanium_cluster_target(context, allow_claimed_contest=True)

    def _has_nearby_repair_marker(self, context: TurnContext) -> bool:
        # Lane claims are only written on ore tiles, so scanning every visible tile
        # is unnecessary work on hot builder turns.
        for ore_position in context.visible_ore_tiles:
            if manhattan_distance(context.position, ore_position) > self.config.route_health_local_radius:
                continue
            claim = self._visible_lane_claim(context.tiles.get(ore_position), context)
            if claim is None:
                continue
            _owner_id, status = claim
            if status == ClaimLaneStatus.REPAIR:
                return True
        return False

    def _has_local_visible_team_titanium_harvester(self, context: TurnContext) -> bool:
        for ore_position in context.visible_ore_tiles:
            if manhattan_distance(context.position, ore_position) > self.config.route_health_local_radius:
                continue
            tile = context.tiles.get(ore_position)
            if (
                tile is not None
                and tile.environment == Environment.ORE_TITANIUM
                and tile.building_type == EntityType.HARVESTER
                and tile.building_team == context.team
            ):
                return True
        return False

    def _should_scan_route_health(
        self,
        context: TurnContext,
        *,
        has_repair_marker: bool | None = None,
        has_local_harvester: bool | None = None,
    ) -> bool:
        if (
            self.pending_harvester is not None
            or self.builder_state == BuilderStateV3.ROUTE_HOME_SAFE
            or self.route_resume_target is not None
        ):
            return True
        repair_marker_present = has_repair_marker
        if repair_marker_present is None:
            repair_marker_present = self._has_nearby_repair_marker(context)
        if repair_marker_present:
            return True
        local_harvester_present = has_local_harvester
        if local_harvester_present is None:
            local_harvester_present = self._has_local_visible_team_titanium_harvester(context)
        if not local_harvester_present:
            return False
        return context.round_num - self.last_route_health_scan_round >= self.config.route_health_scan_interval

    def _flow_gated_axionite_unlocked(self, context: TurnContext, reports: list[LaneHealthReport]) -> bool:
        recent_healthy_harvesters = sum(
            1
            for memory in self.ore_memory.values()
            if memory.environment == Environment.ORE_TITANIUM
            and memory.has_friendly_harvester
            and memory.last_healthy_round >= context.round_num - self.config.flow_window
        )
        if recent_healthy_harvesters < self.config.min_healthy_harvesters_for_axionite:
            return False
        if any(report.status in (RouteHealth.REPAIRABLE_FAULT, RouteHealth.UNSALVAGEABLE_LOCAL) for report in reports):
            return False
        if self.pending_harvester is not None:
            return False
        if self.current_lane_target is not None and self.builder_state in (
            BuilderStateV3.CLAIM_TITANIUM,
            BuilderStateV3.ROUTE_HOME_SAFE,
        ):
            return False
        if len(self.net_titanium_inflow_window) < self.config.flow_window:
            return False
        average_inflow = sum(self.net_titanium_inflow_window) / float(len(self.net_titanium_inflow_window))
        if average_inflow < float(self.config.flow_avg_inflow_threshold):
            return False
        inbound_rounds = sum(1 for evidence in self.inbound_logistics_window if evidence)
        if inbound_rounds < self.config.flow_inbound_min_rounds:
            return False
        return True

    def _economy_bootstrapped(self, context: TurnContext) -> bool:
        if self.observed_first_delivery_round is None:
            return False
        recent_healthy_harvesters = sum(
            1
            for memory in self.ore_memory.values()
            if memory.environment == Environment.ORE_TITANIUM
            and memory.has_friendly_harvester
            and memory.last_healthy_round >= context.round_num - self.config.flow_window
        )
        if recent_healthy_harvesters < self.config.min_healthy_harvesters_for_axionite:
            return False
        sample_window = max(6, self.config.flow_window // 2)
        if len(self.net_titanium_inflow_window) < sample_window:
            return False
        average_inflow = sum(self.net_titanium_inflow_window) / float(len(self.net_titanium_inflow_window))
        return average_inflow >= float(self.config.flow_avg_inflow_threshold)

    def _build_harvester_if_adjacent(self, context: TurnContext, ore_position: Position) -> TurnPlan | None:
        if context.position not in self._ore_adjacent_positions(context, ore_position):
            return None
        ore_tile = context.tiles.get(ore_position)
        if ore_tile is not None and ore_tile.building_type == EntityType.HARVESTER and ore_tile.building_team == context.team:
            return None
        if self.observed_first_delivery_round is None and context.titanium <= self._first_lane_reserve(context):
            return None
        if context.titanium < self._harvester_cost(context):
            return None
        self.pending_harvester = PendingHarvester(ore_position)
        self.current_lane_target = ore_position
        self._mark_lane_commit(context, ore_position)
        self.current_lane_goal = context.position
        self._reset_goal_progress()
        # Freeze a breadcrumb snapshot for return routing so route conversion
        # does not depend on later trail mutations while the builder is stalled.
        self.route_history = list(self.trail)
        if self.route_history and self.route_history[-1] != context.position:
            self.route_history.append(context.position)
        self.route_cursor = len(self.route_history) - 1 if self.route_history else None
        self.builder_state = BuilderStateV3.CLAIM_TITANIUM
        return TurnPlan(
            action=BuildDecision(BuildKind.HARVESTER, ore_position),
            note="policy_fsm_v3 build titanium harvester",
        )

    def _pending_harvester_plan(self, context: TurnContext) -> TurnPlan | None:
        pending = self.pending_harvester
        if pending is None:
            return None
        tile = context.tiles.get(pending.target)
        if tile is not None and tile.building_type == EntityType.HARVESTER and tile.building_team == context.team:
            self.pending_harvester = None
            if not self.route_history:
                self._begin_route_history(context)
            self.builder_state = BuilderStateV3.ROUTE_HOME_SAFE
            self.mode = "return_route"
            return self._safe_route_plan(context)
        if context.position not in self._ore_adjacent_positions(context, pending.target):
            self._mark_lane_failed(pending.target, context)
            self._complete_route_state()
            return None
        if context.titanium < self._harvester_cost(context):
            self._mark_lane_failed(pending.target, context)
            self._complete_route_state()
            return None
        if pending.retries >= 2:
            self._mark_lane_failed(pending.target, context)
            self._complete_route_state()
            return None
        pending.retries += 1
        return TurnPlan(
            action=BuildDecision(BuildKind.HARVESTER, pending.target),
            note="policy_fsm_v3 retry harvester",
        )

    def _route_step_viable(self, context: TurnContext, position: Position) -> bool:
        tile = context.tiles.get(position)
        if tile is None:
            return True
        if not self._tile_passable_for_route(tile):
            return False
        return True

    def _route_next_position(self, context: TurnContext) -> tuple[Position | None, bool]:
        if not self.route_history:
            self._begin_route_history(context)
        if not self.route_history and context.position in self.trail:
            current_index = self.trail.index(context.position)
            if current_index > 0:
                candidate = self.trail[current_index - 1]
                if self._route_step_viable(context, candidate):
                    return candidate, True
                return None, True
        if not self.route_history:
            return None, False
        if self.route_cursor is None:
            self.route_cursor = len(self.route_history) - 1
        if self.route_cursor < 0:
            return None, False
        if self.route_history[self.route_cursor] != context.position:
            for idx in range(len(self.route_history) - 1, -1, -1):
                if self.route_history[idx] == context.position:
                    self.route_cursor = idx
                    break
            else:
                return None, False
        if self.route_cursor <= 0:
            return None, False
        candidate = self.route_history[self.route_cursor - 1]
        if not self._route_step_viable(context, candidate):
            return None, False
        return candidate, False

    def _begin_route_history(self, context: TurnContext) -> None:
        history = list(self.trail)
        if history and history[-1] != context.position:
            history.append(context.position)
        self.route_history = history
        self.route_cursor = len(self.route_history) - 1 if self.route_history else None

    def _find_pipeline_splice(self, context: TurnContext) -> Position | None:
        if self.anchor_position is None:
            return None
        current_distance = manhattan_distance(context.position, self.anchor_position)
        # Only splice into an existing visible artery once the builder is close
        # enough to home that the trace can be trusted all the way into core.
        if current_distance > 6:
            return None
        candidates: list[tuple[int, int, int, Position]] = []
        for direction in CARDINAL_DIRECTIONS:
            position = context.position.add(direction)
            if self._splice_blocked(position):
                continue
            tile = context.tiles.get(position)
            if tile is None or tile.building_team != context.team:
                continue
            if tile.building_type == EntityType.CORE:
                candidates.append((0, manhattan_distance(position, self.anchor_position), 0, position))
                continue
            if tile.building_type not in (EntityType.CONVEYOR, EntityType.BRIDGE):
                continue
            if not self._trace_visible_pipeline(context, position):
                continue
            distance = manhattan_distance(position, self.anchor_position)
            if distance > current_distance:
                continue
            candidates.append((1, distance, 0, position))
        if not candidates:
            return None
        return min(candidates)[3]

    def _trace_visible_pipeline(self, context: TurnContext, start: Position) -> bool:
        seen: set[Position] = set()
        current = start
        for _ in range(12):
            if current in seen:
                return False
            seen.add(current)
            next_hop = self._pipeline_next_hop(context, current)
            if next_hop is None:
                return False
            if next_hop == current:
                return True
            current = next_hop
        return False

    def _current_tile_is_route_sink(self, context: TurnContext) -> bool:
        tile = context.tiles.get(context.position)
        if tile is None or tile.building_team != context.team:
            return False
        if tile.building_type == EntityType.CORE:
            return True
        return tile.building_type in (EntityType.CONVEYOR, EntityType.BRIDGE) and self._trace_visible_pipeline(
            context, context.position
        )

    def _complete_route_state(self) -> None:
        self.pending_harvester = None
        self.current_lane_target = None
        self.current_lane_started_round = -1
        self.current_lane_goal = None
        self.builder_state = BuilderStateV3.FRONTIER_PUSH
        self.mode = "explore"
        self.route_last_position = None
        self.route_stall_counter = 0
        self.route_wait_target = None
        self.route_wait_counter = 0
        self.route_resume_target = None
        self.route_resume_failures = 0
        self.route_pending_bridge = None
        self.goal_stall_counter = 0
        self.last_goal_distance = None
        self.last_claim_target = None
        self.last_claim_round = -1
        self.route_history = []
        self.route_cursor = None
        self.active_search_ticket = None
        self.micro_path = None

    def _recover_route_plan(self, context: TurnContext, *, note: str) -> TurnPlan:
        self.route_resume_failures += 1
        self.route_pending_bridge = None
        self.route_wait_target = None
        self.route_wait_counter = 0
        if self.route_resume_target is None:
            self.route_resume_target = context.position
        if (
            self.route_resume_failures >= self.config.route_stall_turns * 3
            and self.current_lane_target is not None
            and self._small_loop_risk(window=24)
        ):
            self._mark_lane_failed(self.current_lane_target, context)
            self._complete_route_state()
            return TurnPlan(note="policy_fsm_v3 route abandon local cycle")
        escape = self._escape_from_logistics(context, note=note)
        if escape is not None:
            if self.current_lane_target is not None:
                escape.marker = self._claim_marker(context, self.current_lane_target, status=ClaimLaneStatus.ROUTING)
            return escape
        return TurnPlan(
            marker=self._claim_marker(context, self.current_lane_target, status=ClaimLaneStatus.ROUTING),
            note=f"{note} hold",
        )

    def _safe_route_plan(self, context: TurnContext) -> TurnPlan:
        profile_start = perf_counter_ns() if self.profile_enabled else None
        self.builder_state = BuilderStateV3.ROUTE_HOME_SAFE
        self.mode = "return_route"
        result: TurnPlan
        if self.route_resume_target is not None and context.position != self.route_resume_target:
            rejoin = self._move_with_planner(
                context,
                kind=SearchKind.ESCAPE,
                goals={self.route_resume_target},
                waypoint=self.route_resume_target,
                note="policy_fsm_v3 route rejoin",
                frontier_mode=False,
                marker_target=None,
            )
            if self.current_lane_target is not None:
                rejoin.marker = self._claim_marker(context, self.current_lane_target, status=ClaimLaneStatus.ROUTING)
            if rejoin.move is not None:
                self.route_resume_failures = 0
            else:
                self.route_resume_failures += 1
                self.route_pending_bridge = None
                if (
                    self.route_resume_failures >= self.config.route_stall_turns
                    and self.current_lane_target is not None
                    and self._has_fresher_foreign_lane_owner(context, self.current_lane_target)
                ):
                    self._mark_lane_failed(self.current_lane_target, context)
                    self._complete_route_state()
                    result = TurnPlan(note="policy_fsm_v3 route abandon foreign takeover")
                    if profile_start is not None:
                        self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                    return result
            if profile_start is not None:
                self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
            return rejoin
        if self.route_resume_target == context.position:
            self.route_resume_target = None
            self.route_resume_failures = 0
            self.route_pending_bridge = None
        if self.route_pending_bridge is not None:
            bridge_site, bridge_target = self.route_pending_bridge
            tile_at_site = context.tiles.get(bridge_site)
            if (
                tile_at_site is not None
                and tile_at_site.building_type == EntityType.BRIDGE
                and tile_at_site.building_team == context.team
            ):
                entity = context.entities.get(tile_at_site.building_id) if tile_at_site.building_id is not None else None
                if entity is not None and entity.bridge_target == bridge_target:
                    self.route_pending_bridge = None
            if self.route_pending_bridge is not None:
                if bridge_site != context.position and not self._is_adjacent_step(context.position, bridge_site):
                    result = self._recover_route_plan(context, note="policy_fsm_v3 route pending bridge recover")
                    if profile_start is not None:
                        self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                    return result
                if tile_at_site is None or tile_at_site.environment != Environment.EMPTY:
                    result = self._recover_route_plan(context, note="policy_fsm_v3 route pending bridge recover")
                    if profile_start is not None:
                        self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                    return result
                if tile_at_site.building_team not in (None, context.team):
                    result = self._recover_route_plan(context, note="policy_fsm_v3 route pending bridge recover")
                    if profile_start is not None:
                        self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                    return result
                if tile_at_site.building_type in self.PROTECTED_LOGISTICS:
                    result = self._recover_route_plan(context, note="policy_fsm_v3 route pending bridge recover")
                    if profile_start is not None:
                        self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                    return result
                if tile_at_site.building_type not in (None, EntityType.ROAD, EntityType.MARKER):
                    result = self._recover_route_plan(context, note="policy_fsm_v3 route pending bridge recover")
                    if profile_start is not None:
                        self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                    return result
                if context.titanium < self._bridge_cost(context):
                    result = TurnPlan(
                        marker=self._claim_marker(context, self.current_lane_target, status=ClaimLaneStatus.ROUTING),
                        note="policy_fsm_v3 route wait pending bridge titanium",
                    )
                    if profile_start is not None:
                        self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                    return result
                self.route_pending_bridge = None
                result = TurnPlan(
                    marker=self._claim_marker(context, self.current_lane_target, status=ClaimLaneStatus.ROUTING),
                    action=BuildDecision(
                        kind=BuildKind.BRIDGE,
                        position=bridge_site,
                        target=bridge_target,
                        replace_existing=tile_at_site.building_type in (EntityType.ROAD, EntityType.MARKER),
                    ),
                    note="policy_fsm_v3 route stitch bridge",
                )
                if profile_start is not None:
                    self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                return result
        if self._current_tile_is_route_sink(context):
            completed_target = self.current_lane_target
            self._complete_route_state()
            result = TurnPlan(
                marker=self._claim_marker(context, completed_target, status=ClaimLaneStatus.DONE),
                note="policy_fsm_v3 route complete via artery",
            )
            if profile_start is not None:
                self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
            return result

        splice = self._find_pipeline_splice(context)
        used_fallback_direction = False
        if splice is not None:
            next_position = splice
            used_trail = False
        else:
            next_position, used_trail = self._route_next_position(context)
            if next_position is None:
                fallback_direction = self._best_coreward_direction(context, context.position)
                if fallback_direction is None:
                    if self.current_lane_target is not None and not self._current_tile_is_route_sink(context):
                        self.route_resume_target = context.position
                        self.route_pending_bridge = None
                        escape = self._escape_from_logistics(context, note="policy_fsm_v3 route recover")
                        if escape is not None:
                            escape.marker = self._claim_marker(
                                context,
                                self.current_lane_target,
                                status=ClaimLaneStatus.ROUTING,
                            )
                            if profile_start is not None:
                                self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                            return escape
                        result = TurnPlan(
                            marker=self._claim_marker(context, self.current_lane_target, status=ClaimLaneStatus.ROUTING),
                            note="policy_fsm_v3 route recover hold",
                        )
                        if profile_start is not None:
                            self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                        return result
                    self._complete_route_state()
                    note = (
                        "policy_fsm_v3 route complete anchor"
                        if used_trail
                        else "policy_fsm_v3 route complete lost trail"
                    )
                    result = TurnPlan(note=note)
                    if profile_start is not None:
                        self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                    return result
                next_position = context.position.add(fallback_direction)
                used_trail = False
                used_fallback_direction = True

        if self.route_resume_target is None and self.route_wait_target is None:
            if self.route_last_position == context.position:
                self.route_stall_counter += 1
            else:
                self.route_stall_counter = 0
        else:
            self.route_stall_counter = 0
        self.route_last_position = context.position
        if self.route_stall_counter >= self.config.route_stall_turns:
            self.route_stall_counter = 0
            self.route_resume_target = context.position
            self.route_resume_failures += 1
            self.route_pending_bridge = None
            escape = self._escape_from_logistics(context, note="policy_fsm_v3 route stall sidestep")
            if escape is not None:
                if self.current_lane_target is not None:
                    escape.marker = self._claim_marker(context, self.current_lane_target, status=ClaimLaneStatus.ROUTING)
                if profile_start is not None:
                    self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                return escape
            result = TurnPlan(
                marker=self._claim_marker(context, self.current_lane_target, status=ClaimLaneStatus.ROUTING),
                note="policy_fsm_v3 route stall hold",
            )
            if profile_start is not None:
                self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
            return result

        if not self._is_adjacent_step(context.position, next_position):
            result = self._recover_route_plan(context, note="policy_fsm_v3 route gap recover")
            if profile_start is not None:
                self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
            return result

        tile = context.tiles.get(context.position)
        if tile is None:
            self._complete_route_state()
            result = TurnPlan(note="policy_fsm_v3 route abandon missing tile")
            if profile_start is not None:
                self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
            return result
        direction = context.position.direction_to(next_position)
        if direction in DIAGONAL_DIRECTIONS:
            if not self._bridge_target_is_valid(
                context,
                site=context.position,
                target=next_position,
                avoid=None,
            ):
                fallback_direction = self._best_coreward_direction(context, context.position)
                if fallback_direction is None:
                    result = self._recover_route_plan(context, note="policy_fsm_v3 route diagonal recover")
                    if profile_start is not None:
                        self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                    return result
                next_position = context.position.add(fallback_direction)
                direction = fallback_direction
                used_fallback_direction = True
        if used_fallback_direction and not self._direction_preserves_delivery_to_core(context, context.position, direction):
            if not self._allow_pre_delivery_route_detour(context, direction):
                escape = self._escape_from_logistics(context, note="policy_fsm_v3 route preserve delivery")
                if escape is not None:
                    if self.current_lane_target is not None:
                        escape.marker = self._claim_marker(context, self.current_lane_target, status=ClaimLaneStatus.ROUTING)
                    if profile_start is not None:
                        self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                    return escape
                result = TurnPlan(
                    marker=self._claim_marker(context, self.current_lane_target, status=ClaimLaneStatus.ROUTING),
                    note="policy_fsm_v3 route hold preserve delivery",
                )
                if profile_start is not None:
                    self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                return result

        if direction in DIAGONAL_DIRECTIONS and tile.building_type in self.ROUTE_BUILDABLE_TYPES:
            bridge_site = context.position
            bridge_target = next_position
            build_tile = tile
            if build_tile is None:
                result = self._recover_route_plan(context, note="policy_fsm_v3 route bridge recover")
                if profile_start is not None:
                    self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                return result
            if build_tile.environment != Environment.EMPTY:
                result = self._recover_route_plan(context, note="policy_fsm_v3 route bridge recover")
                if profile_start is not None:
                    self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                return result
            if build_tile.building_team not in (None, context.team):
                result = self._recover_route_plan(context, note="policy_fsm_v3 route bridge recover")
                if profile_start is not None:
                    self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                return result
            if build_tile.building_type in self.PROTECTED_LOGISTICS:
                result = self._recover_route_plan(context, note="policy_fsm_v3 route bridge recover")
                if profile_start is not None:
                    self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                return result
            if build_tile.building_type not in (None, EntityType.ROAD, EntityType.MARKER):
                result = self._recover_route_plan(context, note="policy_fsm_v3 route bridge recover")
                if profile_start is not None:
                    self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                return result
            if context.titanium < self._bridge_cost(context):
                self.route_pending_bridge = (bridge_site, bridge_target)
                result = TurnPlan(
                    marker=self._claim_marker(context, self.current_lane_target, status=ClaimLaneStatus.ROUTING),
                    note="policy_fsm_v3 route wait bridge titanium",
                )
                if profile_start is not None:
                    self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                return result
            action = BuildDecision(
                kind=BuildKind.BRIDGE,
                position=bridge_site,
                target=bridge_target,
                replace_existing=build_tile.building_type in (EntityType.ROAD, EntityType.MARKER),
            )
        elif tile.building_type == EntityType.BRIDGE and tile.building_team == context.team:
            entity = context.entities.get(tile.building_id) if tile.building_id is not None else None
            if entity is not None and entity.bridge_target == next_position:
                action = None
            else:
                self._mark_splice_blocked(next_position, context)
                result = self._recover_route_plan(context, note="policy_fsm_v3 route conflicting bridge recover")
                if profile_start is not None:
                    self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                return result
        elif tile.building_type == EntityType.CONVEYOR and tile.building_team == context.team:
            entity = context.entities.get(tile.building_id) if tile.building_id is not None else None
            if entity is not None and entity.direction == direction:
                action = None
            else:
                if self._allow_pre_delivery_conveyor_rewrite(context, direction):
                    if context.titanium < self._conveyor_cost(context):
                        result = TurnPlan(
                            marker=self._claim_marker(context, self.current_lane_target, status=ClaimLaneStatus.ROUTING),
                            note="policy_fsm_v3 route wait rewrite titanium",
                        )
                        if profile_start is not None:
                            self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                        return result
                    allowed, _ = self._build_allowed_candidates(
                        context,
                        [context.position],
                        kind=BuildKind.CONVEYOR,
                        direction=direction,
                        replace_existing=True,
                        allow_protected_rewrite=True,
                    )
                    if not allowed:
                        self._mark_splice_blocked(next_position, context)
                        result = self._recover_route_plan(context, note="policy_fsm_v3 route conflicting conveyor recover")
                        if profile_start is not None:
                            self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                        return result
                    action = BuildDecision(
                        kind=BuildKind.CONVEYOR,
                        position=context.position,
                        direction=direction,
                        replace_existing=True,
                    )
                else:
                    self._mark_splice_blocked(next_position, context)
                    result = self._recover_route_plan(context, note="policy_fsm_v3 route conflicting conveyor recover")
                    if profile_start is not None:
                        self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                    return result
        elif tile.building_type == EntityType.CORE and tile.building_team == context.team:
            action = None
        elif tile.building_type in self.ROUTE_BUILDABLE_TYPES:
            replace_existing = tile.building_type in (EntityType.ROAD, EntityType.MARKER)
            if context.titanium < self._conveyor_cost(context):
                if self.observed_first_delivery_round is None:
                    result = TurnPlan(
                        marker=self._claim_marker(context, self.current_lane_target, status=ClaimLaneStatus.ROUTING),
                        note="policy_fsm_v3 route wait titanium",
                    )
                    if profile_start is not None:
                        self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                    return result
                action = None
            else:
                allowed, _ = self._build_allowed_candidates(
                    context,
                    [context.position],
                    kind=BuildKind.CONVEYOR,
                    direction=direction,
                    replace_existing=replace_existing,
                )
                if not allowed:
                    result = self._recover_route_plan(context, note="policy_fsm_v3 route blocked tile recover")
                    if profile_start is not None:
                        self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                    return result
                action = BuildDecision(
                    kind=BuildKind.CONVEYOR,
                    position=context.position,
                    direction=direction,
                    replace_existing=replace_existing,
                )
        else:
            result = self._recover_route_plan(context, note="policy_fsm_v3 route blocked tile recover")
            if profile_start is not None:
                self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
            return result

        next_tile = context.tiles.get(next_position)
        if next_tile is not None and next_tile.builder_bot_id not in (None, context.entity_id):
            if self.route_wait_target == next_position:
                self.route_wait_counter += 1
            else:
                self.route_wait_target = next_position
                self.route_wait_counter = 1
            if self.route_wait_counter < self.config.route_wait_turns:
                result = TurnPlan(
                    marker=self._claim_marker(context, self.current_lane_target, status=ClaimLaneStatus.ROUTING),
                    action=action,
                    note="policy_fsm_v3 route wait",
                )
                if profile_start is not None:
                    self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                return result
            # Builder traffic should not cause the route builder to abandon the
            # lane outright. Step aside, keep the route state, then rejoin and
            # continue construction once the local congestion clears.
            self.route_resume_target = context.position
            self.route_wait_counter = 0
            self.route_resume_failures += 1
            self.route_pending_bridge = None
            escape = self._escape_from_logistics(context, note="policy_fsm_v3 route congestion sidestep")
            if escape is not None:
                if self.current_lane_target is not None:
                    escape.marker = self._claim_marker(context, self.current_lane_target, status=ClaimLaneStatus.ROUTING)
                if profile_start is not None:
                    self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
                return escape
            result = TurnPlan(
                marker=self._claim_marker(context, self.current_lane_target, status=ClaimLaneStatus.ROUTING),
                note="policy_fsm_v3 route congestion hold",
            )
            if profile_start is not None:
                self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
            return result

        self.route_wait_target = None
        self.route_wait_counter = 0
        self.route_resume_failures = 0
        if splice is None and not used_trail and self.route_cursor is not None and self.route_cursor > 0:
            self.route_cursor -= 1
        result = TurnPlan(
            marker=self._claim_marker(context, self.current_lane_target, status=ClaimLaneStatus.ROUTING),
            action=action,
            move=MoveDecision(direction),
            note="policy_fsm_v3 route safe",
        )
        if profile_start is not None:
            self._profile_record("safe_route_plan", perf_counter_ns() - profile_start)
        return result

    def _apply_diagonal_bridge(self, context: TurnContext, plan: TurnPlan) -> TurnPlan:
        move = plan.move
        if move is None or move.direction not in DIAGONAL_DIRECTIONS:
            return plan
        if (
            self.builder_state != BuilderStateV3.ROUTE_HOME_SAFE
            and self.route_resume_target is None
        ):
            return plan
        if plan.action is not None:
            return plan
        destination = context.position.add(move.direction)
        destination_tile = context.tiles.get(destination)
        if destination_tile is None:
            return plan
        if destination_tile.environment != Environment.EMPTY:
            return plan
        if destination_tile.building_team not in (None, context.team):
            return plan
        if destination_tile.building_type in self.PROTECTED_LOGISTICS:
            return plan
        if self._tile_move_ready(destination_tile):
            return plan
        if destination_tile.building_type not in (None, EntityType.ROAD, EntityType.MARKER):
            return plan
        bridge_target = self._choose_bridge_target(
            context,
            site=destination,
            avoid=context.position,
        )
        if bridge_target is None:
            return plan
        if context.titanium < self._bridge_cost(context):
            return TurnPlan(
                marker=plan.marker,
                action=plan.action,
                note=f"{plan.note} wait bridge titanium".strip(),
            )
        bridge_action = BuildDecision(
            kind=BuildKind.BRIDGE,
            position=destination,
            target=bridge_target,
            replace_existing=destination_tile.building_type in (EntityType.ROAD, EntityType.MARKER),
        )
        return TurnPlan(
            marker=plan.marker,
            action=bridge_action,
            move=move,
            indicator_lines=list(plan.indicator_lines),
            indicator_dots=list(plan.indicator_dots),
            note=plan.note,
        )

    def _logistics_positions(self, context: TurnContext) -> set[Position]:
        self._reset_turn_caches(context)
        if self.turn_logistics_positions_cache is not None:
            return self.turn_logistics_positions_cache
        positions: set[Position] = set()
        if self.anchor_position is not None:
            positions.add(self.anchor_position)
        for tile in context.tiles.values():
            if tile.building_team != context.team:
                continue
            if tile.building_type in self.PROTECTED_LOGISTICS:
                positions.add(tile.position)
        self.turn_logistics_positions_cache = positions
        return positions

    def _choose_escape_adjacent(self, context: TurnContext) -> Position | None:
        logistics = self._logistics_positions(context)
        friendly_positions = self._friendly_builder_positions(context)
        move_ready_adjacent_count = None
        if (
            self.observed_first_delivery_round is None
            and self.builder_state not in (BuilderStateV3.CLAIM_TITANIUM, BuilderStateV3.ROUTE_HOME_SAFE)
        ):
            move_ready_adjacent_count = self._move_ready_adjacent_count(context)
        candidates: list[tuple[int, int, int, int, int, Position]] = []
        for idx, direction in enumerate(CARDINAL_DIRECTIONS):
            position = context.position.add(direction)
            tile = context.tiles.get(position)
            if not self._planner_passable(context, position):
                continue
            if tile is not None and tile.builder_bot_id not in (None, context.entity_id):
                continue
            if not self._fast_step_move_feasible(
                context,
                position,
                tile=tile,
                move_ready_adjacent_count=move_ready_adjacent_count,
            ):
                continue
            penalty = 1 if position in logistics else 0
            candidates.append(
                (
                    penalty,
                    *self._friendly_spacing_penalty(context, position, friendly_positions=friendly_positions),
                    self._recent_visit_count(position),
                    idx,
                    position,
                )
            )
        if not candidates:
            return None
        return min(candidates)[5]

    def _escape_from_logistics(
        self,
        context: TurnContext,
        *,
        note: str,
        target: Position | None = None,
    ) -> TurnPlan | None:
        profile_start = perf_counter_ns() if self.profile_enabled else None
        if target is None:
            target = self._deep_frontier_target(context)
        mask = self._build_action_mask(context, target)
        step = self._choose_masked_step(context, target, mask, frontier_mode=True)
        if step is not None and not self._step_move_feasible(context, step):
            step = None
        if step is None:
            path = find_path_to_best_frontier(context, context.position, max_nodes=128)
            if path:
                step = path[0]
                if not self._step_move_feasible(context, step):
                    step = None
        if step is None:
            step = self._choose_escape_adjacent(context)
        if step is None:
            blocked = self._logistics_positions(context)
            if self._small_loop_risk():
                blocked.update(self.recent_positions[-12:])
            step = choose_bug_escape_step(
                context,
                context.position,
                target,
                recent_positions=self.recent_positions[-24:],
                blocked_positions=blocked,
            )
            if step is not None and not self._step_move_feasible(context, step):
                step = None
        if step is None:
            step = self._choose_unmasked_adjacent(
                context,
                target,
                avoid_logistics=True,
                avoid_recent_loop=self._small_loop_risk(),
            )
        if step is None:
            if profile_start is not None:
                self._profile_record("escape_from_logistics", perf_counter_ns() - profile_start)
            return None
        result = TurnPlan(
            action=self._safe_ground_action(step, context),
            move=MoveDecision(context.position.direction_to(step)),
            note=note,
        )
        result = self._apply_diagonal_bridge(context, result)
        if profile_start is not None:
            self._profile_record("escape_from_logistics", perf_counter_ns() - profile_start)
        return result

    def _enter_patrol(self, context: TurnContext) -> None:
        if self.builder_state != BuilderStateV3.PATROL or self.last_patrol_round != context.round_num - 1:
            self._advance_patrol_cycle()
        self.builder_state = BuilderStateV3.PATROL
        self.last_patrol_round = context.round_num

    def _patrol_target(self, context: TurnContext) -> Position:
        if self.observed_first_delivery_round is None:
            return self._dispersed_exploration_target(context, self._exploration_focus(context))
        mode = self._patrol_mode(context)
        target: Position
        if mode == PatrolMode.DEEP_FRONTIER:
            target = self._deep_frontier_target(context)
        elif mode == PatrolMode.MID_SWEEP:
            target = self._map_center(context)
        else:
            target = self._home_guard_target(context)
        return self._dispersed_exploration_target(context, target)

    def _escape_small_loop_plan(self, context: TurnContext) -> TurnPlan | None:
        if not (self._small_loop_active() or self._small_loop_risk()):
            return None
        for position in set(self.recent_positions[-24:]):
            self._mark_loop_blacklist(position, context)
        self.builder_state = BuilderStateV3.FRONTIER_PUSH
        self.current_lane_target = None
        self.current_lane_started_round = -1
        self.current_lane_goal = None
        self.active_search_ticket = None
        self.micro_path = None
        escape_target = self._map_center(context) if self._border_distance(context, context.position) <= 1 else self._deep_frontier_target(context)
        escape = self._escape_from_logistics(context, note="policy_fsm_v3 small loop escape", target=escape_target)
        if escape is not None:
            return escape
        return TurnPlan(note="policy_fsm_v3 small loop hold")

    def _cached_frontier_waypoint(self, context: TurnContext) -> Position | None:
        waypoint = self.frontier_waypoint_cache
        if waypoint is None:
            return None
        if (
            self._needs_early_ore_discovery(context)
            and self.frontier_waypoint_cache_round < context.round_num - self.config.frontier_cache_refresh_rounds_discovery
        ):
            return None
        if self._local_builder_congestion(context):
            return None
        if not self._in_bounds(context, waypoint):
            return None
        if waypoint == context.position:
            return None
        if self._is_move_blacklisted(waypoint):
            return None
        key = self._tile_key(waypoint)
        seen_round = self.frontier_candidates.get(key)
        if seen_round is not None and seen_round < context.round_num - self.config.frontier_memory_ttl:
            return None
        return waypoint

    def _frontier_waypoint_for_turn(self, context: TurnContext, *, recompute: bool) -> Position:
        cached = self._cached_frontier_waypoint(context)
        if cached is not None:
            return cached
        if recompute:
            waypoint = self._frontier_waypoint(context)
        else:
            waypoint = self._patrol_target(context)
        self.frontier_waypoint_cache = waypoint
        self.frontier_waypoint_cache_round = context.round_num
        return waypoint

    def _frontier_waypoint(self, context: TurnContext) -> Position:
        profile_start = perf_counter_ns() if self.profile_enabled else None
        if not self._economy_bootstrapped(context):
            result = self._exploration_focus(context)
            if profile_start is not None:
                self._profile_record("frontier_waypoint", perf_counter_ns() - profile_start)
            return result
        if self.frontier_candidates:
            center = self._map_center(context)
            ore_focus = self._preferred_ore_focus(context)
            if self.anchor_position is not None:
                dx = 1 if ore_focus.x > self.anchor_position.x else (-1 if ore_focus.x < self.anchor_position.x else 0)
                dy = 1 if ore_focus.y > self.anchor_position.y else (-1 if ore_focus.y < self.anchor_position.y else 0)
                if dx == 0 and dy == 0:
                    dx = 1 if center.x >= self.anchor_position.x else -1
                    dy = 1 if center.y >= self.anchor_position.y else -1
                deep_focus = Position(
                    min(max(ore_focus.x + (dx * 6), 0), context.map_width - 1),
                    min(max(ore_focus.y + (dy * 6), 0), context.map_height - 1),
                )
            else:
                deep_focus = ore_focus
            frontier_focus = (
                deep_focus
                if self.ore_clusters and self.observed_first_delivery_round is not None
                else self._exploration_focus(context)
            )
            best = min(
                (
                    (Position(x, y), seen_round)
                    for (x, y), seen_round in self.frontier_candidates.items()
                    if seen_round >= context.round_num - self.config.frontier_memory_ttl
                    and not self._is_move_blacklisted(Position(x, y))
                ),
                key=lambda item: (
                    -self.frontier_unknown_scores.get(self._tile_key(item[0]), 0),
                    1 if self._border_distance(context, item[0]) <= 1 else 0,
                    1
                    if self.anchor_position is not None
                    and manhattan_distance(item[0], self.anchor_position) <= 4
                    else 0,
                    manhattan_distance(item[0], frontier_focus),
                    -manhattan_distance(item[0], self.anchor_position) if self.anchor_position is not None else 0,
                    self._recent_visit_count(item[0]),
                    -item[1],
                    item[0].x,
                    item[0].y,
                ),
                default=None,
            )
            if best is not None:
                if profile_start is not None:
                    self._profile_record("frontier_waypoint", perf_counter_ns() - profile_start)
                return best[0]
        if self.predicted_enemy_anchor is not None:
            result = self.predicted_enemy_anchor
        else:
            result = self._deep_frontier_target(context)
        if profile_start is not None:
            self._profile_record("frontier_waypoint", perf_counter_ns() - profile_start)
        return result

    def _decide_builder(self, context: TurnContext) -> TurnPlan:
        self.initialise_builder_memory(context)
        self._reset_turn_caches(context)
        self.remember_position(context.position)
        self._remember_recent_position(context.position)
        self._remember_path_history(context.position)
        self.visit_counts[self._tile_key(context.position)] += 1
        remaining_us = self._planner_remaining_us(context)
        needs_belief_refresh = (
            context.round_num - self.last_belief_update_round
            >= self.config.fast_path_belief_refresh_interval
        )

        if self._is_ping_pong() and len(self.recent_positions) >= 2:
            self._mark_loop_blacklist(self.recent_positions[-2], context)

        self._expire_blacklists(context)

        defend_plan = self._choose_defend_plan(context)
        if defend_plan is not None:
            self.builder_state = BuilderStateV3.REACTIVE_DEFEND
            return defend_plan

        loop_escape = self._escape_small_loop_plan(context)
        if loop_escape is not None:
            return loop_escape

        if self.pending_harvester is not None:
            pending_plan = self._pending_harvester_plan(context)
            if pending_plan is not None:
                return pending_plan

        if self.route_resume_target is not None:
            self.builder_state = BuilderStateV3.ROUTE_HOME_SAFE
            self.mode = "return_route"
            return self._safe_route_plan(context)

        if self.builder_state == BuilderStateV3.ROUTE_HOME_SAFE or self.mode == "return_route":
            return self._safe_route_plan(context)

        if self.current_lane_target is not None and self._abandon_stalled_goal(context):
            escape = self._escape_from_logistics(context, note="policy_fsm_v3 goal stall escape")
            if escape is not None:
                return escape

        cached_lane_plan = self._continue_cached_lane_plan(context)
        if cached_lane_plan is not None:
            return cached_lane_plan
        cached_frontier_plan = self._continue_cached_frontier_plan(context)
        if cached_frontier_plan is not None:
            return cached_frontier_plan

        small_loop_risk = self._small_loop_risk()
        target_invalidated = False
        if self.current_lane_target is not None:
            should_validate_target = (
                self.current_lane_target in context.tiles
                or small_loop_risk
                or context.round_num - self.last_lane_viability_round >= self.config.lane_viability_check_interval
            )
            if should_validate_target:
                target_check_start = perf_counter_ns() if self.profile_enabled else None
                self.last_lane_viability_round = context.round_num
                target_invalidated = not self._lane_target_viable(context, self.current_lane_target)
                if target_check_start is not None:
                    self._profile_record("lane_target_viability_check", perf_counter_ns() - target_check_start)
        has_active_route_work = (
            self.pending_harvester is not None
            or self.route_resume_target is not None
            or self.builder_state == BuilderStateV3.ROUTE_HOME_SAFE
        )
        starvation_mode = self._pre_delivery_starvation_mode(context)
        early_ore_discovery = self._needs_early_ore_discovery(context)
        has_local_harvester: bool | None = None
        has_repair_marker: bool | None = None
        slow_path_needed = (
            needs_belief_refresh
            or target_invalidated
            or has_active_route_work
            or small_loop_risk
            or (
                early_ore_discovery
                and context.round_num - self.last_belief_update_round >= self.config.local_harvester_belief_refresh_interval
            )
            or (
                starvation_mode
                and self.current_lane_target is None
                and self.pending_harvester is None
                and self.route_resume_target is None
                and self.builder_state != BuilderStateV3.ROUTE_HOME_SAFE
            )
        )
        if not slow_path_needed:
            has_repair_marker = self._has_nearby_repair_marker(context)
            if has_repair_marker:
                slow_path_needed = True
            elif context.round_num - self.last_route_health_scan_round >= self.config.route_health_scan_interval:
                has_local_harvester = self._has_local_visible_team_titanium_harvester(context)
                slow_path_needed = bool(has_local_harvester)

        if (
            slow_path_needed
            and self.current_lane_target is None
            and not has_active_route_work
            and not starvation_mode
            and self.observed_first_delivery_round is not None
            and remaining_us <= self.config.slow_path_min_remaining_us
        ):
            self._enter_patrol(context)
            frontier_waypoint = self._frontier_waypoint_for_turn(context, recompute=False)
            return self._move_with_planner(
                context,
                kind=SearchKind.FRONTIER,
                goals={frontier_waypoint},
                waypoint=frontier_waypoint,
                note="policy_fsm_v3 cpu-safe patrol",
                frontier_mode=True,
                marker_target=None,
                lay_ground=False,
            )

        if not slow_path_needed:
            self._enter_patrol(context)
            frontier_waypoint = self._frontier_waypoint_for_turn(context, recompute=False)
            return self._move_with_planner(
                context,
                kind=SearchKind.FRONTIER,
                goals={frontier_waypoint},
                waypoint=frontier_waypoint,
                note=f"policy_fsm_v3 patrol {self._patrol_mode(context).name.lower()}",
                frontier_mode=True,
                marker_target=None,
                lay_ground=False,
            )

        belief_refresh_due = context.round_num - self.last_belief_update_round
        refresh_for_core_trigger = needs_belief_refresh or target_invalidated
        refresh_for_repair_marker = (
            bool(has_repair_marker)
            and belief_refresh_due >= self.config.repair_marker_belief_refresh_interval
        )
        should_refresh_belief = (
            refresh_for_core_trigger
            or refresh_for_repair_marker
        )
        if remaining_us > self.config.belief_refresh_min_remaining_us and should_refresh_belief:
            self._update_belief_memory(context)
            if target_invalidated or (needs_belief_refresh and context.visible_ore_tiles):
                self._mark_visible_unreachable_ores(context)
                self._drop_unreachable_visible_lane_target(context)

        if self.current_lane_target is not None and self._abandon_stalled_goal(context):
            escape = self._escape_from_logistics(context, note="policy_fsm_v3 goal stall escape")
            if escape is not None:
                return escape

        reports: list[LaneHealthReport] = []
        if remaining_us > self.config.route_health_scan_min_remaining_us and self._should_scan_route_health(
            context,
            has_repair_marker=has_repair_marker,
            has_local_harvester=has_local_harvester,
        ):
            reports = self._scan_visible_titanium_route_health(context)
            self.last_route_health_scan_round = context.round_num
        throughput_saturated = self._throughput_saturated(context, reports)

        repair_report = self._pick_repairable_lane(context, reports)
        if repair_report is not None:
            return self._repair_lane_plan(context, repair_report)

        congested_report = self._pick_congested_lane(context, reports)
        if congested_report is not None:
            if throughput_saturated:
                expanded = self._expand_congested_lane_plan(context, congested_report)
                if expanded is not None:
                    return expanded
            return self._decongest_lane_plan(context, congested_report)

        if self.current_lane_target is not None:
            adjacent_build = self._build_harvester_if_adjacent(context, self.current_lane_target)
            if adjacent_build is not None:
                return adjacent_build

        previous_target = self.current_lane_target
        target_start = perf_counter_ns() if self.profile_enabled else None
        ore_position, goals = self._active_titanium_target(context)
        if target_start is not None:
            self._profile_record("active_titanium_target", perf_counter_ns() - target_start)
        if ore_position is not None and goals:
            target_changed = ore_position != previous_target
            if target_changed:
                self._reset_goal_progress()
            self.current_lane_target = ore_position
            self._mark_lane_commit(context, ore_position)
            self.current_lane_goal = self._best_lane_goal(context, goals)
            self.builder_state = BuilderStateV3.CLAIM_TITANIUM
            if context.position in goals:
                build_plan = self._build_harvester_if_adjacent(context, ore_position)
                if build_plan is not None:
                    return build_plan
            return self._move_with_planner(
                context,
                kind=SearchKind.ORE,
                goals=goals,
                waypoint=self.current_lane_goal,
                note="policy_fsm_v3 move to titanium",
                frontier_mode=False,
                marker_target=ore_position,
            )

        allow_axionite = self._flow_gated_axionite_unlocked(context, reports)
        if allow_axionite:
            axionite_targets = [
                memory.position
                for memory in self.ore_memory.values()
                if memory.environment == Environment.ORE_AXIONITE
                and memory.last_seen_round >= context.round_num - self.config.ore_memory_ttl
            ]
            if axionite_targets:
                target = min(
                    axionite_targets,
                    key=lambda position: (
                        manhattan_distance(context.position, position),
                        self._recent_visit_count(position),
                        position.x,
                        position.y,
                    ),
                )
                goals = self._ore_adjacent_positions(context, target)
                if goals:
                    waypoint = min(
                        goals,
                        key=lambda goal: (
                            manhattan_distance(context.position, goal),
                            goal.x,
                            goal.y,
                        ),
                    )
                    return self._move_with_planner(
                        context,
                        kind=SearchKind.FRONTIER,
                        goals=goals,
                        waypoint=waypoint,
                        note="policy_fsm_v3 flow-gated axionite scout",
                        frontier_mode=False,
                        marker_target=None,
                        lay_ground=False,
                    )

        self.current_lane_target = None
        self.current_lane_started_round = -1
        self.current_lane_goal = None
        self._reset_goal_progress()
        self._enter_patrol(context)
        frontier_waypoint = self._frontier_waypoint_for_turn(context, recompute=True)
        if frontier_waypoint == context.position:
            frontier_path = find_path_to_best_frontier(context, context.position, max_nodes=96)
            if frontier_path:
                frontier_waypoint = frontier_path[-1]
        return self._move_with_planner(
            context,
            kind=SearchKind.FRONTIER,
            goals={frontier_waypoint},
            waypoint=frontier_waypoint,
            note=f"policy_fsm_v3 patrol {self._patrol_mode(context).name.lower()}",
            frontier_mode=True,
            marker_target=None,
            lay_ground=False,
        )
