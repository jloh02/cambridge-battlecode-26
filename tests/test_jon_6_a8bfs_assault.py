from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cambc import Direction, EntityType, Environment, Position


JON_6_A8_BFS_ROOT = (
    Path(__file__).resolve().parent.parent / "bots" / "jon-6-a8bfs"
)
for module_name in (
    "assault",
    "marker",
    "mode_assaulting",
    "navigation",
    "perception",
    "utils",
    "states",
):
    sys.modules.pop(module_name, None)
if str(JON_6_A8_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_6_A8_BFS_ROOT))
importlib.invalidate_caches()

import assault as a8_assault  # noqa: E402
import mode_assaulting as a8_mode_assaulting  # noqa: E402
from states import BuilderMode  # noqa: E402


def _enemy(x, y, entity_type, direction=None):
    return a8_assault.VisibleEnemy(
        position=Position(x, y),
        entity_type=entity_type,
        direction=direction,
    )


def _empty_grid(*positions):
    return {(p.x, p.y): {"env": Environment.EMPTY, "last_seen": 50} for p in positions}


class _StubLogger:
    def log(self, _msg): pass
    def print(self, _msg): pass


class _StubController:
    def __init__(
        self,
        *,
        position,
        movable_by_position=None,
        buildings_by_position=None,
        destroyable_positions=None,
        fireable_positions=None,
        current_round=20,
        entity_id=7,
        map_width=10,
        map_height=10,
        can_build_sentinel=False,
        action_cooldown=0,
        global_resources=(0, 0),
        sentinel_cost=(40, 0),
    ):
        self._position = position
        self._movable_by_position = {
            key: set(value) for key, value in (movable_by_position or {}).items()
        }
        self._buildings_by_position = {}
        self._entities_by_id = {}
        next_building_id = 1000
        for key, building in (buildings_by_position or {}).items():
            building_id = building.get("id", next_building_id)
            next_building_id = max(next_building_id, building_id + 1)
            self._buildings_by_position[key] = {
                "id": building_id,
                "type": building["type"],
                "team": building.get("team"),
            }
            self._entities_by_id[building_id] = self._buildings_by_position[key]
        self._destroyable_positions = set(destroyable_positions or set())
        self._fireable_positions = set(fireable_positions or set())
        self._current_round = current_round
        self._entity_id = entity_id
        self._map_width = map_width
        self._map_height = map_height
        self._can_build_sentinel = can_build_sentinel
        self._action_cooldown = action_cooldown
        self._global_resources = global_resources
        self._sentinel_cost = sentinel_cost
        self.moved: list[Direction] = []
        self.built_sentinels: list[tuple[Position, Direction]] = []
        self.destroyed_positions: list[Position] = []
        self.fired_positions: list[Position] = []

    def get_position(self, _id=None): return self._position
    def get_current_round(self): return self._current_round
    def get_id(self): return self._entity_id
    def get_team(self, _id=None):
        if _id is None:
            return 1
        entity = self._entities_by_id.get(_id)
        if entity is None:
            return 1
        return entity.get("team")
    def get_entity_type(self, entity_id):
        entity = self._entities_by_id.get(entity_id)
        return None if entity is None else entity.get("type")
    def get_map_width(self): return self._map_width
    def get_map_height(self): return self._map_height
    def get_tile_building_id(self, pos):
        building = self._buildings_by_position.get((pos.x, pos.y))
        return None if building is None else building["id"]
    def can_build_road(self, _pos): return False
    def build_road(self, _pos): pass
    def can_move(self, direction):
        return direction in self._movable_by_position.get(
            (self._position.x, self._position.y),
            set(),
        )

    def move(self, direction):
        self.moved.append(direction)
        self._position = self._position.add(direction)
    def can_destroy(self, pos): return (pos.x, pos.y) in self._destroyable_positions
    def destroy(self, pos):
        self.destroyed_positions.append(pos)
        self._buildings_by_position.pop((pos.x, pos.y), None)
    def can_build_sentinel(self, _pos, _direction): return self._can_build_sentinel
    def build_sentinel(self, pos, direction): self.built_sentinels.append((pos, direction))
    def can_fire(self, pos): return (pos.x, pos.y) in self._fireable_positions
    def fire(self, pos): self.fired_positions.append(pos)
    def get_action_cooldown(self): return self._action_cooldown
    def get_global_resources(self): return self._global_resources
    def get_sentinel_cost(self): return self._sentinel_cost

    def get_nearby_entities(self): return []
    def get_nearby_tiles(self): return []
    def get_nearby_units(self): return []


def _mode_bot(
    grid,
    *,
    start,
    core_pos,
    visible_enemy_targets=None,
    visible_positions=None,
    confirmed_enemy_harvesters=None,
    predicted_enemy_harvesters=None,
    connected_friendly_conveyors=None,
    claimed_assault_anchor_keys=None,
):
    return SimpleNamespace(
        grid=grid,
        logger=_StubLogger(),
        builder_mode=BuilderMode.ASSAULTING,
        is_assault_role=True,
        core_pos=core_pos,
        spawn_pos=start,
        spawn_slot=0,
        pathfinding_state={
            "path": [],
            "known_obstacles": set(),
            "temporary_obstacles": {},
            "current_target": None,
        },
        assault_bootstrap_state={
            "target": None,
            "path": [],
            "expires_round": -1,
            "blocked_turns": 0,
            "start_round": -1,
            "last_position": None,
            "checkpoint_chunk": None,
        },
        assault_opening_escape_complete=False,
        harvester_anchor=None,
        harvester_anchor_last_seen_round=-9999,
        assault_anchor_blacklist={},
        assault_anchor_status=None,
        assault_exhausted_regions=[],
        assault_exhausted_sectors={},
        visible_enemy_targets=list(visible_enemy_targets or []),
        visible_enemy_passable_buildings=set(),
        visible_positions=set(visible_positions or set(grid)),
        visible_friendly_builders=[],
        confirmed_enemy_harvesters=dict(confirmed_enemy_harvesters or {}),
        predicted_enemy_harvesters=list(predicted_enemy_harvesters or []),
        recent_assault_waypoints={},
        claimed_assault_anchor_keys=set(claimed_assault_anchor_keys or set()),
        claimed_explore_chunks=set(),
        connected_friendly_conveyors=dict(connected_friendly_conveyors or {}),
        symmetry_candidates=("ROT180", "MIRROR_X", "MIRROR_Y"),
        best_symmetry_mode="ROT180",
        symmetry_confidence="LOW",
        enemy_core_anchor=None,
        enemy_core_exact=False,
        last_enemy_core_position=None,
        last_symmetry_update_round=-9999,
        assault_known_ore_count=0,
        discovery_turns_without_new_ore=0,
        titanium_locations=set(),
        assault_subrole="scout",
        assault_scout_state={
            "target": None,
            "chunk": None,
            "anchor": None,
            "expires_round": -1,
        },
        assault_claim_state={
            "anchor": None,
            "last_round": -9999,
        },
        assault_execute_state={
            "subplan": None,
            "anchor": None,
            "ring": None,
            "direction": None,
            "wait_turns": 0,
            "fire_wait_turns": 0,
        },
        assault_committed_site=None,
        assault_committed_site_round=-9999,
        turn_profile={},
        assault_nav_failure_count=0,
        assault_progress_stall_count=0,
        assault_best_dist_to_ring=9999,
        assault_nav_progress_target=None,
        stats={},
        last_assault_profile_ring_key=None,
    )


def _live_assessment(*, anchor_visible_now=True):
    return a8_assault.AnchorAssessment(
        status=a8_assault.ANCHOR_LIVE,
        cluster_size=1,
        enemy_logistics_count=1,
        adjacent_friendly_connected=0,
        friendly_ring_sentinels=0,
        pressure_established=False,
        anchor_visible_now=anchor_visible_now,
        useful_ring_sides=1,
        resolved_ring_sides=1,
        remaining_high_value_sites=1,
        best_logistics_gain=1,
        useful_sites=1,
        immediate_sites=1,
        clearable_sites=0,
        best_marginal_value=1,
    )


def _site(
    *,
    harvester: Position,
    ring: Position,
    ring_classification: str,
    target_type: EntityType = EntityType.CONVEYOR,
) -> a8_assault.AssaultSite:
    return a8_assault.AssaultSite(
        harvester_position=harvester,
        ring_position=ring,
        sentinel_direction=Direction.NORTHWEST,
        target=a8_assault.SiteTarget(Position(harvester.x, harvester.y + 1), target_type, 1),
        hits_core_center=False,
        has_high_value_target=False,
        cluster_size=1,
        usable_sides=2,
        immediate_open_sides=2,
        turns_to_useful_shot=0,
        threatened=False,
        ring_classification=ring_classification,
        marginal_value=4,
        uncovered_logistics_gain=1,
        uncovered_target_count=1,
        total_target_value=4,
    )


def test_bootstrap_prefers_outward_progress_over_immediate_backtrack():
    start = Position(5, 5)
    core_pos = Position(3, 3)
    bot = _mode_bot(
        _empty_grid(start, Position(6, 6), Position(4, 4)),
        start=start,
        core_pos=core_pos,
    )
    bot.assault_bootstrap_state["start_round"] = 10
    bot.assault_bootstrap_state["last_position"] = (4, 4)
    ct = _StubController(
        position=start,
        movable_by_position={
            (5, 5): {Direction.SOUTHEAST, Direction.NORTHWEST},
        },
    )

    preferred = a8_mode_assaulting._bootstrap_preferred_direction(bot, ct)

    assert preferred == Direction.SOUTHEAST


def test_bootstrap_allows_bounded_backstep_in_corridor_after_repeated_blocks():
    start = Position(6, 6)
    core_pos = Position(3, 3)
    bot = _mode_bot(
        _empty_grid(start, Position(5, 6)),
        start=start,
        core_pos=core_pos,
    )
    bot.assault_bootstrap_state["start_round"] = 10
    ct = _StubController(
        position=start,
        current_round=10,
        movable_by_position={
            (6, 6): {Direction.WEST},
        },
    )

    assert a8_mode_assaulting.execute_bootstrap_egress_only(bot, ct) is True
    assert ct.get_position() == start
    assert bot.assault_bootstrap_state["blocked_turns"] == 1

    assert a8_mode_assaulting.execute_bootstrap_egress_only(bot, ct) is True
    assert ct.get_position() == start
    assert bot.assault_bootstrap_state["blocked_turns"] == 2

    assert a8_mode_assaulting.execute_bootstrap_egress_only(bot, ct) is True
    assert ct.get_position() == Position(5, 6)
    assert bot.assault_bootstrap_state["blocked_turns"] == 0
    assert bot.assault_subrole == "bootstrap"


def test_bootstrap_completes_after_signal_once_outside_shell():
    start = Position(7, 7)
    core_pos = Position(3, 3)
    ore = Position(7, 6)
    grid = _empty_grid(start, ore)
    grid[(ore.x, ore.y)] = {
        "env": Environment.ORE_TITANIUM,
        "last_seen": 50,
    }
    bot = _mode_bot(
        grid,
        start=start,
        core_pos=core_pos,
        visible_positions={(start.x, start.y), (ore.x, ore.y)},
    )
    bot.assault_bootstrap_state["start_round"] = 10
    ct = _StubController(position=start, current_round=12, map_width=30, map_height=30)

    a8_mode_assaulting._refresh_bootstrap_egress_state(bot, ct)

    assert bot.assault_opening_escape_complete is True
    assert a8_mode_assaulting.bootstrap_egress_active(bot, ct) is False


def test_predicted_enemy_harvesters_keep_unseen_mirrored_ore_candidates():
    predicted = a8_assault.build_predicted_enemy_harvesters(
        current_position=Position(14, 46),
        grid={},
        map_width=21,
        map_height=50,
        my_team=1,
        surviving_modes=("ROT180",),
        best_mode="ROT180",
        enemy_core_anchor=Position(10, 1),
        remembered_ores={
            Position(14, 43),
            Position(16, 45),
            Position(15, 43),
            Position(13, 42),
        },
        confirmed_enemy_harvesters=set(),
        current_anchor=None,
    )

    assert predicted
    assert any(candidate.unseen_sides > 0 for candidate in predicted)
    assert any(candidate.position.y < 10 for candidate in predicted)


def test_choose_best_site_for_harvester_prefers_immediate_ring_over_clearable_pressure():
    harvester = Position(12, 12)
    immediate_ring = Position(12, 11)
    clearable_ring = Position(13, 12)
    enemies = [_enemy(12, 12, EntityType.HARVESTER)]

    def _classify(*, ring_position, **_kwargs):
        if ring_position == immediate_ring:
            return a8_assault.RING_IMMEDIATE
        if ring_position == clearable_ring:
            return a8_assault.RING_CLEARABLE
        return a8_assault.RING_BLOCKED

    def _target_summary(*, ring_position, **_kwargs):
        if ring_position == immediate_ring:
            return (
                a8_assault.SiteTarget(Position(12, 13), EntityType.CONVEYOR, 1),
                4,
                4,
                1,
                1,
                False,
            )
        if ring_position == clearable_ring:
            return (
                a8_assault.SiteTarget(Position(14, 12), EntityType.CONVEYOR, 1),
                12,
                12,
                3,
                3,
                False,
            )
        return (None, 0, 0, 0, 0, False)

    with patch.object(a8_assault, "classify_ring_site", side_effect=_classify):
        with patch.object(a8_assault, "visible_threat_score", return_value=0):
            with patch.object(
                a8_assault,
                "_candidate_sentinel_directions",
                return_value=[Direction.NORTHWEST],
            ):
                with patch.object(a8_assault, "_target_summary_for_site", side_effect=_target_summary):
                    with patch.object(a8_assault, "_front_vector", return_value=(0, 0)):
                        site = a8_assault.choose_best_site_for_harvester(
                            harvester_position=harvester,
                            current_position=Position(8, 16),
                            enemies=enemies,
                            map_width=30,
                            map_height=30,
                            grid={},
                            my_team=1,
                            actor_id=7,
                            allow_exploratory_fallback=False,
                        )

    assert site is not None
    assert site.ring_position == immediate_ring


def test_choose_best_site_for_harvester_prefers_friendly_marker_ring_over_empty_ring():
    harvester = Position(12, 12)
    friendly_marker_ring = Position(12, 11)
    empty_ring = Position(13, 12)
    enemies = [_enemy(12, 12, EntityType.HARVESTER)]
    grid = _empty_grid(harvester, friendly_marker_ring, empty_ring)
    grid[(friendly_marker_ring.x, friendly_marker_ring.y)].update(
        {"building": EntityType.MARKER, "building_team": 1}
    )

    def _target_summary(*, ring_position, **_kwargs):
        if ring_position in {friendly_marker_ring, empty_ring}:
            return (
                a8_assault.SiteTarget(Position(12, 13), EntityType.CONVEYOR, 1),
                4,
                4,
                1,
                1,
                False,
            )
        return (None, 0, 0, 0, 0, False)

    with patch.object(a8_assault, "visible_threat_score", return_value=0):
        with patch.object(
            a8_assault,
            "_candidate_sentinel_directions",
            return_value=[Direction.NORTHWEST],
        ):
            with patch.object(a8_assault, "_target_summary_for_site", side_effect=_target_summary):
                with patch.object(a8_assault, "_front_vector", return_value=(0, 0)):
                    site = a8_assault.choose_best_site_for_harvester(
                        harvester_position=harvester,
                        current_position=Position(8, 16),
                        enemies=enemies,
                        map_width=30,
                        map_height=30,
                        grid=grid,
                        my_team=1,
                        actor_id=7,
                        allow_exploratory_fallback=False,
                    )

    assert site is not None
    assert site.ring_position == friendly_marker_ring


def test_choose_best_site_for_harvester_prefers_enemy_road_ring_over_enemy_conveyor_ring():
    harvester = Position(12, 12)
    enemy_road_ring = Position(12, 11)
    enemy_conveyor_ring = Position(13, 12)
    enemies = [_enemy(12, 12, EntityType.HARVESTER)]
    grid = _empty_grid(harvester, enemy_road_ring, enemy_conveyor_ring)
    grid[(enemy_road_ring.x, enemy_road_ring.y)].update(
        {"building": EntityType.ROAD, "building_team": 2}
    )
    grid[(enemy_conveyor_ring.x, enemy_conveyor_ring.y)].update(
        {"building": EntityType.CONVEYOR, "building_team": 2}
    )

    def _target_summary(*, ring_position, **_kwargs):
        if ring_position in {enemy_road_ring, enemy_conveyor_ring}:
            return (
                a8_assault.SiteTarget(Position(12, 13), EntityType.CONVEYOR, 1),
                4,
                4,
                1,
                1,
                False,
            )
        return (None, 0, 0, 0, 0, False)

    with patch.object(a8_assault, "visible_threat_score", return_value=0):
        with patch.object(
            a8_assault,
            "_candidate_sentinel_directions",
            return_value=[Direction.NORTHWEST],
        ):
            with patch.object(a8_assault, "_target_summary_for_site", side_effect=_target_summary):
                with patch.object(a8_assault, "_front_vector", return_value=(0, 0)):
                    site = a8_assault.choose_best_site_for_harvester(
                        harvester_position=harvester,
                        current_position=Position(8, 16),
                        enemies=enemies,
                        map_width=30,
                        map_height=30,
                        grid=grid,
                        my_team=1,
                        actor_id=7,
                        allow_exploratory_fallback=False,
                    )

    assert site is not None
    assert site.ring_position == enemy_road_ring


def test_best_visible_site_abandons_visible_anchor_without_actionable_site():
    harvester = Position(12, 12)
    bot = _mode_bot(
        _empty_grid(harvester),
        start=Position(5, 5),
        core_pos=Position(3, 3),
        visible_enemy_targets=[_enemy(12, 12, EntityType.HARVESTER)],
    )
    ct = _StubController(position=Position(10, 10), current_round=40, map_width=30, map_height=30)

    with patch.object(
        a8_mode_assaulting,
        "_anchor_assessment",
        return_value=_live_assessment(),
    ):
        with patch.object(
            a8_assault,
            "choose_best_site_for_harvester",
            return_value=None,
        ) as mock_choose:
            site, abandoned = a8_mode_assaulting._best_visible_site(
                bot,
                ct,
                live_anchor=harvester,
                cache={},
            )

    assert site is None
    assert abandoned == [(harvester, a8_mode_assaulting.NO_ACTIONABLE_SITE_REASON)]
    assert mock_choose.call_args.kwargs["allow_exploratory_fallback"] is False


def test_best_visible_site_prefers_deeper_anchor_toward_enemy_core_focus():
    shallow_anchor = Position(6, 14)
    deep_anchor = Position(14, 6)
    shallow_site = a8_assault.AssaultSite(
        harvester_position=shallow_anchor,
        ring_position=Position(6, 13),
        sentinel_direction=Direction.NORTHWEST,
        target=a8_assault.SiteTarget(Position(6, 15), EntityType.CONVEYOR, 1),
        hits_core_center=False,
        has_high_value_target=False,
        cluster_size=2,
        usable_sides=2,
        immediate_open_sides=2,
        turns_to_useful_shot=0,
        threatened=False,
        ring_classification=a8_assault.RING_IMMEDIATE,
        marginal_value=4,
        uncovered_logistics_gain=1,
        uncovered_target_count=1,
        total_target_value=4,
    )
    deep_site = a8_assault.AssaultSite(
        harvester_position=deep_anchor,
        ring_position=Position(14, 5),
        sentinel_direction=Direction.NORTHWEST,
        target=a8_assault.SiteTarget(Position(14, 7), EntityType.CONVEYOR, 1),
        hits_core_center=False,
        has_high_value_target=False,
        cluster_size=2,
        usable_sides=2,
        immediate_open_sides=2,
        turns_to_useful_shot=0,
        threatened=False,
        ring_classification=a8_assault.RING_IMMEDIATE,
        marginal_value=4,
        uncovered_logistics_gain=1,
        uncovered_target_count=1,
        total_target_value=4,
    )
    bot = _mode_bot(
        _empty_grid(shallow_anchor, deep_anchor),
        start=Position(5, 5),
        core_pos=Position(3, 28),
        visible_enemy_targets=[
            _enemy(shallow_anchor.x, shallow_anchor.y, EntityType.HARVESTER),
            _enemy(deep_anchor.x, deep_anchor.y, EntityType.HARVESTER),
        ],
    )
    bot.enemy_core_anchor = Position(16, 2)
    ct = _StubController(position=Position(3, 20), current_round=40, map_width=30, map_height=30)

    def _site_for_anchor(*, harvester_position, **_kwargs):
        if harvester_position == shallow_anchor:
            return shallow_site
        if harvester_position == deep_anchor:
            return deep_site
        return None

    with patch.object(
        a8_mode_assaulting,
        "_anchor_assessment",
        return_value=_live_assessment(),
    ):
        with patch.object(
            a8_assault,
            "choose_best_site_for_harvester",
            side_effect=_site_for_anchor,
        ):
            site, abandoned = a8_mode_assaulting._best_visible_site(
                bot,
                ct,
                live_anchor=None,
                cache={},
            )

    assert abandoned == []
    assert site == deep_site


def test_committed_visible_site_stays_valid_past_commit_ttl():
    harvester = Position(12, 12)
    ring = Position(12, 11)
    site = a8_assault.AssaultSite(
        harvester_position=harvester,
        ring_position=ring,
        sentinel_direction=Direction.NORTHWEST,
        target=a8_assault.SiteTarget(Position(12, 13), EntityType.CONVEYOR, 1),
        hits_core_center=False,
        has_high_value_target=False,
        cluster_size=1,
        usable_sides=2,
        immediate_open_sides=2,
        turns_to_useful_shot=0,
        threatened=False,
        ring_classification=a8_assault.RING_IMMEDIATE,
        marginal_value=4,
        uncovered_logistics_gain=1,
        uncovered_target_count=1,
        total_target_value=4,
    )
    grid = _empty_grid(ring, Position(13, 12), Position(12, 13), Position(11, 12))
    bot = _mode_bot(
        grid,
        start=Position(5, 5),
        core_pos=Position(3, 3),
        visible_enemy_targets=[_enemy(12, 12, EntityType.HARVESTER)],
    )
    bot.assault_committed_site = site
    bot.assault_committed_site_round = 20
    ct = _StubController(position=Position(6, 6), current_round=40, map_width=30, map_height=30)

    assert a8_mode_assaulting._committed_site_is_valid(
        bot,
        ct,
        site,
        assessment=_live_assessment(),
    )


def test_execute_abandons_visible_anchor_without_exploratory_rerank():
    harvester = Position(12, 12)
    bot = _mode_bot(
        _empty_grid(harvester),
        start=Position(5, 5),
        core_pos=Position(3, 3),
        visible_enemy_targets=[_enemy(12, 12, EntityType.HARVESTER)],
    )
    bot.assault_opening_escape_complete = True
    bot.harvester_anchor = harvester
    bot.harvester_anchor_last_seen_round = 40
    ct = _StubController(position=Position(10, 10), current_round=40, map_width=30, map_height=30)
    live_assessment = _live_assessment()

    with patch.object(a8_mode_assaulting, "_execute_opening_escape", return_value=False):
        with patch.object(a8_mode_assaulting, "_update_enemy_inference"):
            with patch.object(
                a8_mode_assaulting,
                "_anchor_assessment",
                return_value=live_assessment,
            ):
                with patch.object(
                    a8_mode_assaulting,
                    "_reusable_committed_site",
                    return_value=(None, live_assessment),
                ):
                    with patch.object(
                        a8_mode_assaulting,
                        "_best_site_for_anchor",
                        side_effect=AssertionError(
                            "visible anchors should not use exploratory reranking"
                        ),
                    ):
                        with patch.object(
                            a8_mode_assaulting,
                            "_best_visible_site",
                            return_value=(
                                None,
                                [(harvester, a8_mode_assaulting.NO_ACTIONABLE_SITE_REASON)],
                            ),
                        ):
                            with patch.object(
                                a8_mode_assaulting.navigation,
                                "assault_navigate",
                                return_value=(False, None),
                            ) as mock_navigate:
                                with patch.object(
                                    a8_mode_assaulting,
                                    "_choose_scout_target",
                                    return_value=Position(2, 2),
                                ):
                                    a8_mode_assaulting.execute(bot, ct)

    assert bot.harvester_anchor is None
    assert mock_navigate.called


def test_execute_build_subplan_times_out_when_build_window_never_opens():
    harvester = Position(12, 12)
    ring = Position(12, 11)
    site = _site(
        harvester=harvester,
        ring=ring,
        ring_classification=a8_assault.RING_IMMEDIATE,
    )
    bot = _mode_bot(
        _empty_grid(ring),
        start=Position(5, 5),
        core_pos=Position(3, 3),
    )
    bot.harvester_anchor = harvester
    bot.harvester_anchor_last_seen_round = 40
    bot.assault_execute_state = {
        "subplan": "BUILD",
        "anchor": (harvester.x, harvester.y),
        "ring": (ring.x, ring.y),
        "direction": site.sentinel_direction.name,
        "wait_turns": a8_mode_assaulting.BUILD_WINDOW_WAIT_TTL - 1,
        "fire_wait_turns": 0,
    }
    ct = _StubController(
        position=Position(11, 11),
        current_round=40,
        map_width=30,
        map_height=30,
        can_build_sentinel=False,
        action_cooldown=1,
        global_resources=(100, 0),
        sentinel_cost=(40, 0),
    )

    assert a8_mode_assaulting._execute_build_subplan(bot, ct, site) is True
    assert bot.harvester_anchor is None
    assert bot.assault_committed_site is None


def test_classify_ring_site_distinguishes_friendly_and_enemy_roads_and_markers():
    ring = Position(12, 11)
    cases = (
        (EntityType.ROAD, 1, a8_assault.RING_IMMEDIATE),
        (EntityType.ROAD, 2, a8_assault.RING_CLEARABLE),
        (EntityType.MARKER, 1, a8_assault.RING_IMMEDIATE),
        (EntityType.MARKER, 2, a8_assault.RING_CLEARABLE),
        (EntityType.BRIDGE, 2, a8_assault.RING_CLEARABLE),
    )

    for building_type, building_team, expected in cases:
        grid = _empty_grid(ring)
        grid[(ring.x, ring.y)] = {
            "env": Environment.EMPTY,
            "last_seen": 50,
            "building": building_type,
            "building_team": building_team,
        }

        assert a8_assault.classify_ring_site(
            grid=grid,
            ring_position=ring,
            map_width=30,
            map_height=30,
            my_team=1,
            actor_id=7,
        ) == expected


def test_execute_build_subplan_destroys_friendly_road_and_marker_before_build_attempt():
    harvester = Position(12, 12)
    ring = Position(12, 11)
    site = _site(
        harvester=harvester,
        ring=ring,
        ring_classification=a8_assault.RING_IMMEDIATE,
    )

    for building_type in (EntityType.ROAD, EntityType.MARKER):
        grid = _empty_grid(ring)
        grid[(ring.x, ring.y)] = {
            "env": Environment.EMPTY,
            "last_seen": 50,
            "building": building_type,
            "building_team": 1,
        }
        bot = _mode_bot(grid, start=Position(5, 5), core_pos=Position(3, 3))
        bot.harvester_anchor = harvester
        bot.harvester_anchor_last_seen_round = 40
        bot.assault_execute_state = {
            "subplan": "BUILD",
            "anchor": (harvester.x, harvester.y),
            "ring": (ring.x, ring.y),
            "direction": site.sentinel_direction.name,
            "wait_turns": 0,
            "fire_wait_turns": 0,
        }
        ct = _StubController(
            position=Position(11, 11),
            current_round=40,
            map_width=30,
            map_height=30,
            can_build_sentinel=False,
            action_cooldown=1,
            global_resources=(100, 0),
            sentinel_cost=(40, 0),
            buildings_by_position={
                (ring.x, ring.y): {"type": building_type, "team": 1},
            },
            destroyable_positions={(ring.x, ring.y)},
        )

        assert a8_mode_assaulting._execute_build_subplan(bot, ct, site) is True
        assert ct.destroyed_positions == [ring]


def test_execute_clear_then_build_subplan_treats_enemy_passable_ring_buildings_as_clearable():
    harvester = Position(12, 12)
    ring = Position(12, 11)

    for building_type in (EntityType.ROAD, EntityType.MARKER, EntityType.BRIDGE):
        site = _site(
            harvester=harvester,
            ring=ring,
            ring_classification=a8_assault.RING_CLEARABLE,
            target_type=building_type,
        )
        grid = _empty_grid(ring)
        grid[(ring.x, ring.y)] = {
            "env": Environment.EMPTY,
            "last_seen": 50,
            "building": building_type,
            "building_team": 2,
        }
        bot = _mode_bot(grid, start=Position(5, 5), core_pos=Position(3, 3))
        bot.harvester_anchor = harvester
        bot.harvester_anchor_last_seen_round = 40
        bot.assault_execute_state = {
            "subplan": "CLEAR_THEN_BUILD",
            "anchor": (harvester.x, harvester.y),
            "ring": (ring.x, ring.y),
            "direction": site.sentinel_direction.name,
            "wait_turns": 0,
            "fire_wait_turns": 0,
        }
        ct = _StubController(
            position=Position(11, 11),
            current_round=40,
            map_width=30,
            map_height=30,
            movable_by_position={(11, 11): {Direction.EAST}},
            buildings_by_position={
                (ring.x, ring.y): {"type": building_type, "team": 2},
            },
            fireable_positions={(ring.x, ring.y)},
        )

        assert a8_mode_assaulting._execute_clear_then_build_subplan(bot, ct, site) is True
        assert ct.get_position() == ring
        assert ct.fired_positions == []

        assert a8_mode_assaulting._execute_clear_then_build_subplan(bot, ct, site) is True
        assert ct.fired_positions == [ring]
