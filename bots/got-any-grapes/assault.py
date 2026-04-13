from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from cambc import Direction, EntityType, Environment, Position


ALL_EIGHT_DIRECTIONS = (
    Direction.NORTH,
    Direction.NORTHEAST,
    Direction.EAST,
    Direction.SOUTHEAST,
    Direction.SOUTH,
    Direction.SOUTHWEST,
    Direction.WEST,
    Direction.NORTHWEST,
)
CARDINAL_DIRECTIONS = (
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
)
DIAGONAL_DIRECTIONS = (
    Direction.NORTHEAST,
    Direction.SOUTHEAST,
    Direction.SOUTHWEST,
    Direction.NORTHWEST,
)
STEP_BY_DIRECTION = {
    Direction.NORTH: (0, -1),
    Direction.NORTHEAST: (1, -1),
    Direction.EAST: (1, 0),
    Direction.SOUTHEAST: (1, 1),
    Direction.SOUTH: (0, 1),
    Direction.SOUTHWEST: (-1, 1),
    Direction.WEST: (-1, 0),
    Direction.NORTHWEST: (-1, -1),
}
SYMMETRY_MODES = ("ROT180", "MIRROR_X", "MIRROR_Y")
SYMMETRY_ORDER = {mode: index for index, mode in enumerate(SYMMETRY_MODES)}

CONNECTED_LOGISTICS_TYPES = {
    EntityType.HARVESTER,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
    EntityType.BRIDGE,
    EntityType.FOUNDRY,
}
PASSABLE_RING_BUILDINGS = {
    None,
    EntityType.ROAD,
    EntityType.MARKER,
}
CLEARABLE_RING_BUILDINGS = {
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
}


def _profile_bump(profile: dict | None, key: str, value: int = 1) -> None:
    if profile is None:
        return
    profile[key] = profile.get(key, 0) + value


def _profile_max(profile: dict | None, key: str, value: int) -> None:
    if profile is None:
        return
    profile[key] = max(profile.get(key, value), value)
HARASSABLE_PASSABLE_BUILDINGS = {
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
}
TURRET_TYPES = {
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.LAUNCHER,
}
THREATENING_TYPES = TURRET_TYPES | {EntityType.BUILDER_BOT}
ANCHOR_LIVE = "LIVE"
ANCHOR_CAPTURED = "CAPTURED_BY_US"
ANCHOR_DRIED = "DRIED_OUT"
ANCHOR_SATURATED = "SATURATED"
ANCHOR_GOOD_ENOUGH = "GOOD_ENOUGH_MOVE_ON"
RING_IMMEDIATE = "IMMEDIATE"
RING_CLEARABLE = "CLEARABLE"
RING_UNSEEN = "UNSEEN"
RING_BLOCKED = "BLOCKED"
RING_BUILT = "BUILT"
RING_OCCUPIED = "OCCUPIED"
RING_OPEN = "OPEN"
SOURCE_RANK = {
    "CONFIRMED": 0,
    "MIRRORED_FRIENDLY_HARVESTER": 1,
    "MIRRORED_ORE": 2,
}


@dataclass(frozen=True, slots=True)
class VisibleEnemy:
    position: Position
    entity_type: EntityType
    direction: Direction | None = None


@dataclass(frozen=True, slots=True)
class SiteTarget:
    position: Position
    entity_type: EntityType
    priority: int


@dataclass(frozen=True, slots=True)
class AssaultSite:
    harvester_position: Position
    ring_position: Position
    sentinel_direction: Direction
    target: SiteTarget
    hits_core_center: bool
    has_high_value_target: bool
    cluster_size: int
    usable_sides: int
    immediate_open_sides: int
    turns_to_useful_shot: int
    threatened: bool
    ring_classification: str
    marginal_value: int
    uncovered_logistics_gain: int
    uncovered_target_count: int
    total_target_value: int


@dataclass(frozen=True, slots=True)
class AnchorAssessment:
    status: str
    cluster_size: int
    enemy_logistics_count: int
    adjacent_friendly_connected: int
    friendly_ring_sentinels: int
    pressure_established: bool
    anchor_visible_now: bool
    useful_ring_sides: int
    resolved_ring_sides: int
    remaining_high_value_sites: int
    best_logistics_gain: int
    useful_sites: int
    immediate_sites: int
    clearable_sites: int
    best_marginal_value: int


@dataclass(frozen=True, slots=True)
class PredictedHarvester:
    position: Position
    source: str
    source_rank: int
    usable_sides: int
    immediate_open_sides: int
    clearable_sides: int
    unseen_sides: int
    travel_distance: int
    distance_to_core_anchor: int
    same_lane: bool
    mode: str | None


@dataclass(frozen=True, slots=True)
class SymmetryModeScore:
    mode: str
    compared_weight: int
    mismatch_weight: int

    @property
    def mismatch_ratio(self) -> float:
        if self.compared_weight <= 0:
            return 1.0
        return self.mismatch_weight / self.compared_weight


def manhattan(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def distance_sq(a: Position, b: Position) -> int:
    dx = a.x - b.x
    dy = a.y - b.y
    return (dx * dx) + (dy * dy)


def is_in_bounds(position: Position, map_width: int, map_height: int) -> bool:
    return 0 <= position.x < map_width and 0 <= position.y < map_height


def mirror_position(
    position: Position,
    mode: str,
    *,
    map_width: int,
    map_height: int,
) -> Position:
    max_x = map_width - 1
    max_y = map_height - 1
    if mode == "ROT180":
        return Position(max_x - position.x, max_y - position.y)
    if mode == "MIRROR_X":
        return Position(max_x - position.x, position.y)
    return Position(position.x, max_y - position.y)


def _tile_weight(env: Environment | None) -> int:
    if env in {
        Environment.WALL,
        Environment.ORE_TITANIUM,
        Environment.ORE_AXIONITE,
    }:
        return 2
    return 1


def build_symmetry_informative_tiles(
    *,
    grid: dict[tuple[int, int], dict],
    core_pos: Position | None,
) -> tuple[tuple[int, int, int, int, int, Position, Environment], ...]:
    if core_pos is None:
        return ()

    informative_tiles = []
    for key, data in grid.items():
        env = data.get("env")
        if env is None:
            continue
        pos = Position(key[0], key[1])
        informative_tiles.append(
            (
                -_tile_weight(env),
                -int(data.get("last_seen", 0)),
                -distance_sq(pos, core_pos),
                pos.x,
                pos.y,
                pos,
                env,
            )
        )

    informative_tiles.sort()
    return tuple(informative_tiles)


def evaluate_symmetry_modes(
    *,
    grid: dict[tuple[int, int], dict],
    map_width: int,
    map_height: int,
    core_pos: Position | None,
    previous_modes: tuple[str, ...] = SYMMETRY_MODES,
    max_samples: int = 128,
    informative_tiles: tuple[
        tuple[int, int, int, int, int, Position, Environment],
        ...,
    ] | None = None,
) -> tuple[tuple[str, ...], str | None, str, tuple[SymmetryModeScore, ...]]:
    if core_pos is None:
        return previous_modes, None, "LOW", ()

    ordered_tiles = (
        informative_tiles
        if informative_tiles is not None
        else build_symmetry_informative_tiles(grid=grid, core_pos=core_pos)
    )
    samples = ordered_tiles[:max_samples]

    scores = []
    surviving = []
    for mode in SYMMETRY_MODES:
        compared_weight = 0
        mismatch_weight = 0
        for _, _, _, _, _, pos, env in samples:
            mirrored = mirror_position(
                pos, mode, map_width=map_width, map_height=map_height
            )
            mirrored_data = grid.get((mirrored.x, mirrored.y))
            mirrored_env = None if mirrored_data is None else mirrored_data.get("env")
            if mirrored_env is None:
                continue
            weight = _tile_weight(env)
            compared_weight += weight
            if mirrored_env != env:
                mismatch_weight += weight
        score = SymmetryModeScore(
            mode=mode,
            compared_weight=compared_weight,
            mismatch_weight=mismatch_weight,
        )
        scores.append(score)
        if compared_weight < 12 or (5 * mismatch_weight) <= compared_weight:
            surviving.append(mode)

    if not surviving:
        surviving = list(previous_modes)

    if not surviving:
        return (), None, "LOW", tuple(scores)

    surviving_scores = {score.mode: score for score in scores}
    best_mode = min(
        surviving,
        key=lambda mode: (
            surviving_scores.get(mode, SymmetryModeScore(mode, 0, 0)).mismatch_ratio,
            -surviving_scores.get(mode, SymmetryModeScore(mode, 0, 0)).compared_weight,
            SYMMETRY_ORDER[mode],
        ),
    )
    best_score = surviving_scores.get(best_mode, SymmetryModeScore(best_mode, 0, 0))
    if len(surviving) == 1 and best_score.compared_weight >= 24:
        confidence = "HIGH"
    elif len(surviving) <= 2:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"
    return tuple(surviving), best_mode, confidence, tuple(scores)


_SENTINEL_ATTACK_CACHE: dict[tuple[int, int, str, int], frozenset[tuple[int, int]]] = {}


def sentinel_attack_tiles(
    origin: Position,
    direction: Direction,
    *,
    max_range_sq: int = 32,
) -> frozenset[tuple[int, int]]:
    cache_key = (origin.x, origin.y, direction.name, max_range_sq)
    cached = _SENTINEL_ATTACK_CACHE.get(cache_key)
    if cached is not None:
        return cached
    attackable: set[tuple[int, int]] = set()
    dx, dy = STEP_BY_DIRECTION[direction]
    for step in range(1, 7):
        bx = origin.x + dx * step
        by = origin.y + dy * step
        bdx = bx - origin.x
        bdy = by - origin.y
        if bdx * bdx + bdy * bdy > max_range_sq:
            break
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                cx = bx + ox
                cy = by + oy
                rel_x = cx - origin.x
                rel_y = cy - origin.y
                if rel_x == 0 and rel_y == 0:
                    continue
                if rel_x * dx + rel_y * dy <= 0:
                    continue
                if rel_x * rel_x + rel_y * rel_y > max_range_sq:
                    continue
                attackable.add((cx, cy))
    result = frozenset(attackable)
    _SENTINEL_ATTACK_CACHE[cache_key] = result
    return result


def can_feed_sentinel(
    anchor_harvester: Position,
    ring_position: Position,
    sentinel_direction: Direction,
) -> bool:
    feed_direction = ring_position.direction_to(anchor_harvester)
    if feed_direction not in CARDINAL_DIRECTIONS:
        return False
    if sentinel_direction in DIAGONAL_DIRECTIONS:
        return True
    return feed_direction != sentinel_direction


def connected_enemy_logistics_cluster(
    anchor_harvester: Position,
    enemies: list[VisibleEnemy],
    *,
    profile: dict | None = None,
) -> set[Position]:
    _profile_bump(profile, "assault_cluster_calls")
    logistics_positions = {
        enemy.position
        for enemy in enemies
        if enemy.entity_type in CONNECTED_LOGISTICS_TYPES
    }
    if anchor_harvester not in logistics_positions:
        _profile_bump(profile, "assault_cluster_misses")
        return set()

    visited: set[Position] = set()
    queue: deque[Position] = deque([anchor_harvester])

    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for direction in CARDINAL_DIRECTIONS:
            candidate = current.add(direction)
            if candidate in logistics_positions and candidate not in visited:
                queue.append(candidate)

    _profile_bump(profile, "assault_cluster_nodes", len(visited))
    _profile_max(profile, "assault_cluster_peak", len(visited))
    return visited


def classify_ring_site(
    *,
    grid: dict[tuple[int, int], dict],
    ring_position: Position,
    map_width: int,
    map_height: int,
    my_team,
    actor_id: int | None = None,
) -> str:
    hard_state = classify_visible_ring_state(
        grid=grid,
        ring_position=ring_position,
        map_width=map_width,
        map_height=map_height,
        my_team=my_team,
        actor_id=actor_id,
    )
    if hard_state == RING_OPEN:
        return RING_IMMEDIATE
    if hard_state == RING_CLEARABLE:
        return RING_CLEARABLE
    if hard_state in {RING_BUILT, RING_OCCUPIED, RING_BLOCKED}:
        return RING_BLOCKED

    data = grid.get((ring_position.x, ring_position.y))
    if data is None or data.get("env") is None:
        return RING_UNSEEN
    return RING_BLOCKED


def classify_visible_ring_state(
    *,
    grid: dict[tuple[int, int], dict],
    ring_position: Position,
    map_width: int,
    map_height: int,
    my_team,
    actor_id: int | None = None,
) -> str:
    if not is_in_bounds(ring_position, map_width, map_height):
        return RING_BLOCKED

    data = grid.get((ring_position.x, ring_position.y))
    if data is None or data.get("env") is None:
        return RING_UNSEEN
    if data.get("env") != Environment.EMPTY:
        return RING_BLOCKED

    if (
        data.get("building") == EntityType.SENTINEL
        and data.get("building_team") == my_team
    ):
        return RING_BUILT

    entity = data.get("entity")
    if entity is not None:
        if entity != EntityType.BUILDER_BOT:
            return RING_OCCUPIED
        if actor_id is None or data.get("id") != actor_id:
            return RING_OCCUPIED

    building = data.get("building")
    if building in PASSABLE_RING_BUILDINGS:
        return RING_OPEN
    if (
        building in CLEARABLE_RING_BUILDINGS
        and data.get("building_team") is not None
        and data.get("building_team") != my_team
    ):
        return RING_CLEARABLE
    return RING_BLOCKED


def prune_confirmed_enemy_harvesters(
    *,
    confirmed_enemy_harvesters: dict[tuple[int, int], int],
    current_round: int,
    visible_positions: set[tuple[int, int]],
    enemies: list[VisibleEnemy],
    ttl: int = 48,
) -> dict[tuple[int, int], int]:
    visible_harvester_positions = {
        (enemy.position.x, enemy.position.y)
        for enemy in enemies
        if enemy.entity_type == EntityType.HARVESTER
    }
    return {
        position_key: seen_round
        for position_key, seen_round in confirmed_enemy_harvesters.items()
        if current_round - seen_round <= ttl
        and (
            position_key not in visible_positions
            or position_key in visible_harvester_positions
        )
    }


def choose_alternate_harvester_anchor(
    *,
    current_position: Position,
    current_anchor: Position,
    enemies: list[VisibleEnemy],
    predicted_enemy_harvesters: list[PredictedHarvester],
    visible_positions: set[tuple[int, int]] | None = None,
) -> Position | None:
    visible_candidates = []
    seen_visible = set()
    visible_positions = visible_positions or set()
    for enemy in enemies:
        if enemy.entity_type != EntityType.HARVESTER:
            continue
        if enemy.position == current_anchor:
            continue
        key = (enemy.position.x, enemy.position.y)
        if key in seen_visible:
            continue
        seen_visible.add(key)
        visible_candidates.append(enemy.position)

    if visible_candidates:
        return min(
            visible_candidates,
            key=lambda position: (
                manhattan(current_position, position),
                position.x,
                position.y,
            ),
        )

    visible_keys = set(seen_visible) | visible_positions
    for candidate in predicted_enemy_harvesters:
        if candidate.position == current_anchor:
            continue
        key = (candidate.position.x, candidate.position.y)
        if key in visible_keys:
            continue
        return candidate.position
    return None


def choose_predicted_scout_anchor(
    *,
    predicted_enemy_harvesters: list[PredictedHarvester],
    spawn_slot: int | None,
    current_round: int,
) -> Position | None:
    if not predicted_enemy_harvesters:
        return None
    slot = 0 if spawn_slot is None else spawn_slot
    epoch = current_round // 12
    index = (slot + epoch) % len(predicted_enemy_harvesters)
    return predicted_enemy_harvesters[index].position


def _target_priority(
    enemy: VisibleEnemy,
    *,
    anchor_harvester: Position,
    cluster_positions: set[Position],
    prefer_core_over_logistics: bool = False,
) -> int | None:
    if enemy.entity_type in TURRET_TYPES:
        return 0
    if enemy.position == anchor_harvester:
        return None
    if enemy.entity_type == EntityType.CORE:
        return 1 if prefer_core_over_logistics else 2
    if enemy.position in cluster_positions:
        return 2 if prefer_core_over_logistics else 1
    return None


def _target_value(
    enemy: VisibleEnemy,
    *,
    prefer_core_over_logistics: bool,
) -> int:
    if enemy.entity_type in TURRET_TYPES:
        return 12
    if enemy.entity_type == EntityType.CORE:
        return 8 if prefer_core_over_logistics else 6
    return 7 if not prefer_core_over_logistics else 4


def _is_cluster_logistics_target(
    enemy: VisibleEnemy,
    *,
    harvester_position: Position,
    cluster_positions: set[Position],
) -> bool:
    return (
        enemy.position != harvester_position
        and enemy.position in cluster_positions
        and enemy.entity_type in CONNECTED_LOGISTICS_TYPES
    )


def _target_summary_for_site(
    *,
    harvester_position: Position,
    ring_position: Position,
    sentinel_direction: Direction,
    enemies: list[VisibleEnemy],
    cluster_positions: set[Position],
    map_width: int,
    enemies_by_key: dict[tuple[int, int], VisibleEnemy] | None = None,
    legal_fire_fn=None,
    covered_targets: set[Position] | None = None,
    prefer_core_over_logistics: bool = False,
    enemy_core_center: Position | None = None,
    profile: dict | None = None,
) -> tuple[SiteTarget | None, int, int, int, int, bool]:
    covered_targets = covered_targets or set()
    _profile_bump(profile, "assault_target_summary_calls")
    attack_tiles = sentinel_attack_tiles(ring_position, sentinel_direction)
    if enemies_by_key is None:
        enemy_candidates = enemies
        _profile_bump(profile, "assault_target_summary_enemy_scans", len(enemies))
    else:
        enemy_candidates = (
            enemy
            for tile_key in attack_tiles
            for enemy in (enemies_by_key.get(tile_key),)
            if enemy is not None
        )
        _profile_bump(profile, "assault_target_summary_tile_checks", len(attack_tiles))
    best_target: tuple[tuple[int, int, int, int], SiteTarget] | None = None
    total_target_value = 0
    marginal_value = 0
    uncovered_logistics_gain = 0
    uncovered_target_count = 0
    hits_core_center = False
    if enemy_core_center is not None and (enemy_core_center.x, enemy_core_center.y) in attack_tiles:
        hits_core_center = True
    for enemy in enemy_candidates:
        if (enemy.position.x, enemy.position.y) not in attack_tiles:
            continue
        if enemy.entity_type == EntityType.CORE and (
            enemy_core_center is None or enemy.position != enemy_core_center
        ):
            continue
        priority = _target_priority(
            enemy,
            anchor_harvester=harvester_position,
            cluster_positions=cluster_positions,
            prefer_core_over_logistics=prefer_core_over_logistics,
        )
        if priority is None:
            continue
        value = _target_value(
            enemy,
            prefer_core_over_logistics=prefer_core_over_logistics,
        )
        total_target_value += value
        if enemy.position not in covered_targets:
            marginal_value += value
            uncovered_target_count += 1
            if _is_cluster_logistics_target(
                enemy,
                harvester_position=harvester_position,
                cluster_positions=cluster_positions,
            ):
                uncovered_logistics_gain += 1
        subpriority = 0 if enemy.entity_type == EntityType.HARVESTER else 1
        target_score = (
            priority,
            subpriority,
            manhattan(ring_position, enemy.position),
            enemy.position.x + (enemy.position.y * map_width),
        )
        target = SiteTarget(enemy.position, enemy.entity_type, priority)
        if best_target is None or target_score < best_target[0]:
            best_target = (target_score, target)
    return (
        None if best_target is None else best_target[1],
        total_target_value,
        marginal_value,
        uncovered_logistics_gain,
        uncovered_target_count,
        hits_core_center,
    )


def _front_vector(
    *,
    harvester_position: Position,
    current_position: Position,
    enemies: list[VisibleEnemy],
    cluster_positions: set[Position],
    enemy_core_center: Position | None,
) -> tuple[int, int]:
    if enemy_core_center is not None:
        return (
            enemy_core_center.x - harvester_position.x,
            enemy_core_center.y - harvester_position.y,
        )

    weighted_dx = 0
    weighted_dy = 0
    for enemy in enemies:
        if enemy.position == harvester_position:
            continue
        weight = 0
        if enemy.entity_type in TURRET_TYPES:
            weight = 12
        elif enemy.entity_type == EntityType.CORE:
            weight = 10
        elif (
            enemy.position in cluster_positions
            and enemy.entity_type in CONNECTED_LOGISTICS_TYPES
        ):
            weight = 6
        elif enemy.entity_type == EntityType.BUILDER_BOT:
            weight = 2
        if weight <= 0:
            continue
        weighted_dx += (enemy.position.x - harvester_position.x) * weight
        weighted_dy += (enemy.position.y - harvester_position.y) * weight

    if weighted_dx or weighted_dy:
        return weighted_dx, weighted_dy

    return (
        harvester_position.x - current_position.x,
        harvester_position.y - current_position.y,
    )


def _ring_frontness(
    *,
    harvester_position: Position,
    ring_position: Position,
    front_dx: int,
    front_dy: int,
) -> int:
    return (
        (ring_position.x - harvester_position.x) * front_dx
        + (ring_position.y - harvester_position.y) * front_dy
    )


def _direction_alignment_score(
    direction: Direction,
    *,
    front_dx: int,
    front_dy: int,
) -> int:
    step_dx, step_dy = STEP_BY_DIRECTION[direction]
    return (step_dx * front_dx) + (step_dy * front_dy)


def _candidate_sentinel_directions(
    *,
    harvester_position: Position,
    ring_position: Position,
    front_dx: int,
    front_dy: int,
    committed_ring_position: Position | None = None,
    committed_direction: Direction | None = None,
    limit: int = 3,
) -> list[Direction]:
    ranked: list[tuple[tuple[int, int, int, int], Direction]] = []
    for index, direction in enumerate(ALL_EIGHT_DIRECTIONS):
        if not can_feed_sentinel(harvester_position, ring_position, direction):
            continue
        alignment = _direction_alignment_score(
            direction,
            front_dx=front_dx,
            front_dy=front_dy,
        )
        ranked.append(
            (
                (
                    0
                    if committed_ring_position == ring_position
                    and committed_direction == direction
                    else 1,
                    -alignment,
                    0 if direction in DIAGONAL_DIRECTIONS else 1,
                    index,
                ),
                direction,
            )
        )
    ranked.sort(key=lambda item: item[0])
    directions = [direction for _, direction in ranked[:limit]]
    if directions:
        return directions
    return [
        direction
        for direction in ALL_EIGHT_DIRECTIONS
        if can_feed_sentinel(harvester_position, ring_position, direction)
    ]


def _pressure_score_for_site(
    *,
    target: SiteTarget | None,
    hits_core_center: bool,
    marginal_value: int,
    uncovered_logistics_gain: int,
    uncovered_target_count: int,
) -> int:
    pressure = marginal_value * 24
    pressure += uncovered_logistics_gain * 120
    pressure += uncovered_target_count * 16
    if hits_core_center:
        pressure += 5000
    if target is not None and target.entity_type in TURRET_TYPES:
        pressure += 1200
    elif target is not None and target.entity_type == EntityType.CORE:
        pressure += 800
    return pressure


def visible_threat_score(
    *,
    ring_position: Position,
    enemies: list[VisibleEnemy],
    profile: dict | None = None,
) -> int:
    _profile_bump(profile, "assault_threat_score_calls")
    _profile_bump(profile, "assault_threat_enemy_scans", len(enemies))
    threat = 0
    for enemy in enemies:
        if enemy.entity_type in TURRET_TYPES:
            if enemy.direction is not None:
                if (ring_position.x, ring_position.y) in sentinel_attack_tiles(enemy.position, enemy.direction):
                    threat += 2
                    continue
            if distance_sq(enemy.position, ring_position) <= 18:
                threat += 1
        elif enemy.entity_type == EntityType.BUILDER_BOT and manhattan(enemy.position, ring_position) <= 1:
            threat += 1
    return threat


def _ring_side_counts(
    *,
    harvester_position: Position,
    grid: dict[tuple[int, int], dict],
    map_width: int,
    map_height: int,
    my_team,
    actor_id: int | None = None,
) -> tuple[int, int, int]:
    immediate = 0
    clearable = 0
    unseen = 0
    for direction in CARDINAL_DIRECTIONS:
        ring_position = harvester_position.add(direction)
        classification = classify_ring_site(
            grid=grid,
            ring_position=ring_position,
            map_width=map_width,
            map_height=map_height,
            my_team=my_team,
            actor_id=actor_id,
        )
        if classification == RING_IMMEDIATE:
            immediate += 1
        elif classification == RING_CLEARABLE:
            clearable += 1
        elif classification == RING_UNSEEN:
            unseen += 1
    return immediate, clearable, unseen


def _friendly_connected_neighbor_count(
    harvester_position: Position,
    connected_friendly_conveyors,
) -> int:
    if not connected_friendly_conveyors:
        return 0
    connected_keys = set(connected_friendly_conveyors)
    count = 0
    for direction in CARDINAL_DIRECTIONS:
        neighbor = harvester_position.add(direction)
        if (neighbor.x, neighbor.y) in connected_keys:
            count += 1
    return count


def _friendly_ring_sentinel_state(
    harvester_position: Position,
    *,
    enemies: list[VisibleEnemy],
    grid: dict[tuple[int, int], dict] | None,
    my_team,
) -> tuple[set[Position], set[Position]]:
    if grid is None or my_team is None:
        return set(), set()

    sentinel_positions: set[Position] = set()
    covered_targets: set[Position] = set()
    visible_enemy_positions = {enemy.position for enemy in enemies}

    for direction in CARDINAL_DIRECTIONS:
        ring_position = harvester_position.add(direction)
        data = grid.get((ring_position.x, ring_position.y))
        if data is None:
            continue
        if (
            data.get("building") is not EntityType.SENTINEL
            or data.get("building_team") != my_team
        ):
            continue
        sentinel_positions.add(ring_position)
        sentinel_direction = data.get("building_dir")
        if sentinel_direction is None:
            continue
        attack_tiles = sentinel_attack_tiles(ring_position, sentinel_direction)
        covered_targets.update(
            position for position in visible_enemy_positions if (position.x, position.y) in attack_tiles
        )

    return sentinel_positions, covered_targets


def _fallback_anchor_site(
    *,
    harvester_position: Position,
    map_width: int,
    map_height: int,
    grid: dict[tuple[int, int], dict] | None,
    my_team,
    actor_id: int | None,
    blocked: set[Position],
) -> AssaultSite | None:
    if grid is None or my_team is None:
        return None

    for direction in CARDINAL_DIRECTIONS:
        ring_position = harvester_position.add(direction)
        if ring_position in blocked:
            continue
        if not is_in_bounds(ring_position, map_width, map_height):
            continue
        classification = classify_ring_site(
            grid=grid,
            ring_position=ring_position,
            map_width=map_width,
            map_height=map_height,
            my_team=my_team,
            actor_id=actor_id,
        )
        if classification not in {RING_IMMEDIATE, RING_CLEARABLE}:
            continue
        for sentinel_direction in ALL_EIGHT_DIRECTIONS:
            if can_feed_sentinel(harvester_position, ring_position, sentinel_direction):
                return AssaultSite(
                    harvester_position=harvester_position,
                    ring_position=ring_position,
                    sentinel_direction=sentinel_direction,
                    target=SiteTarget(harvester_position, EntityType.HARVESTER, 3),
                    hits_core_center=False,
                    has_high_value_target=False,
                    cluster_size=1,
                    usable_sides=1,
                    immediate_open_sides=1 if classification == RING_IMMEDIATE else 0,
                    turns_to_useful_shot=1 if classification == RING_CLEARABLE else 0,
                    threatened=False,
                    ring_classification=classification,
                    marginal_value=1,
                    uncovered_logistics_gain=0,
                    uncovered_target_count=0,
                    total_target_value=1,
                )
    return None


def rank_assault_sites_for_harvester(
    *,
    harvester_position: Position,
    current_position: Position,
    enemies: list[VisibleEnemy],
    map_width: int,
    map_height: int,
    grid: dict[tuple[int, int], dict] | None = None,
    my_team=None,
    actor_id: int | None = None,
    blocked_ring_positions: set[Position] | None = None,
    legal_fire_fn=None,
    enemy_core_center: Position | None = None,
    current_anchor: Position | None = None,
    site_bias: int = 0,
    connected_friendly_conveyors=None,
    committed_ring_position: Position | None = None,
    committed_direction: Direction | None = None,
    allow_exploratory_fallback: bool = True,
    profile: dict | None = None,
) -> list[AssaultSite]:
    _profile_bump(profile, "assault_rank_calls")
    _profile_bump(profile, "assault_rank_enemy_count_total", len(enemies))
    _profile_max(profile, "assault_rank_enemy_count_peak", len(enemies))
    blocked = blocked_ring_positions or set()
    cluster_positions = connected_enemy_logistics_cluster(
        harvester_position,
        enemies,
        profile=profile,
    )
    if not cluster_positions:
        cluster_positions = {harvester_position}
    _profile_max(profile, "assault_rank_cluster_peak", len(cluster_positions))

    immediate_open_sides = 0
    clearable_sides = 0
    unseen_sides = 0
    if grid is not None and my_team is not None:
        immediate_open_sides, clearable_sides, unseen_sides = _ring_side_counts(
            harvester_position=harvester_position,
            grid=grid,
            map_width=map_width,
            map_height=map_height,
            my_team=my_team,
            actor_id=actor_id,
        )
    usable_sides = immediate_open_sides + clearable_sides

    friendly_ring_sentinels, _covered_targets = _friendly_ring_sentinel_state(
        harvester_position,
        enemies=enemies,
        grid=grid,
        my_team=my_team,
    )
    enemies_by_key = {
        (enemy.position.x, enemy.position.y): enemy
        for enemy in enemies
    }
    front_dx, front_dy = _front_vector(
        harvester_position=harvester_position,
        current_position=current_position,
        enemies=enemies,
        cluster_positions=cluster_positions,
        enemy_core_center=enemy_core_center,
    )

    ranked: list[tuple[tuple[int, ...], AssaultSite]] = []
    ring_candidates: list[tuple[tuple[int, ...], Position, str, int, int]] = []
    for direction_index, site_direction in enumerate(CARDINAL_DIRECTIONS):
        _profile_bump(profile, "assault_ring_positions_considered")
        ring_position = harvester_position.add(site_direction)
        if ring_position in blocked:
            continue
        if not is_in_bounds(ring_position, map_width, map_height):
            continue

        classification = RING_IMMEDIATE
        if grid is not None and my_team is not None:
            classification = classify_ring_site(
                grid=grid,
                ring_position=ring_position,
                map_width=map_width,
                map_height=map_height,
                my_team=my_team,
                actor_id=actor_id,
            )
        if classification not in {RING_IMMEDIATE, RING_CLEARABLE}:
            continue

        threat_score = visible_threat_score(
            ring_position=ring_position,
            enemies=enemies,
            profile=profile,
        )
        ring_candidates.append(
            (
                (
                    0 if classification == RING_IMMEDIATE else 1,
                    0 if committed_ring_position == ring_position else 1,
                    0 if threat_score == 0 else 1,
                    -_ring_frontness(
                        harvester_position=harvester_position,
                        ring_position=ring_position,
                        front_dx=front_dx,
                        front_dy=front_dy,
                    ),
                    manhattan(current_position, ring_position),
                    (direction_index - site_bias) % len(CARDINAL_DIRECTIONS),
                    direction_index,
                    ring_position.x + (ring_position.y * map_width),
                ),
                ring_position,
                classification,
                threat_score,
                direction_index,
            )
        )

    ring_candidates.sort(key=lambda item: item[0])

    for _, ring_position, classification, threat_score, direction_index in ring_candidates:
        for sentinel_direction in _candidate_sentinel_directions(
            harvester_position=harvester_position,
            ring_position=ring_position,
            front_dx=front_dx,
            front_dy=front_dy,
            committed_ring_position=committed_ring_position,
            committed_direction=committed_direction,
        ):
            _profile_bump(profile, "assault_site_direction_candidates")
            threatened = threat_score > 0
            turns_to_shot = 0 if classification == RING_IMMEDIATE else 1
            (
                best_target,
                total_target_value,
                marginal_value,
                uncovered_logistics_gain,
                uncovered_target_count,
                hits_core_center,
            ) = _target_summary_for_site(
                harvester_position=harvester_position,
                ring_position=ring_position,
                sentinel_direction=sentinel_direction,
                enemies=enemies,
                enemies_by_key=enemies_by_key,
                cluster_positions=cluster_positions,
                map_width=map_width,
                legal_fire_fn=legal_fire_fn,
                covered_targets=_covered_targets,
                enemy_core_center=enemy_core_center,
                profile=profile,
            )
            site = AssaultSite(
                harvester_position=harvester_position,
                ring_position=ring_position,
                sentinel_direction=sentinel_direction,
                target=best_target or SiteTarget(harvester_position, EntityType.HARVESTER, 0),
                hits_core_center=hits_core_center,
                has_high_value_target=best_target is not None,
                cluster_size=len(cluster_positions),
                usable_sides=usable_sides,
                immediate_open_sides=immediate_open_sides,
                turns_to_useful_shot=turns_to_shot,
                threatened=threatened,
                ring_classification=classification,
                marginal_value=marginal_value,
                uncovered_logistics_gain=uncovered_logistics_gain,
                uncovered_target_count=uncovered_target_count,
                total_target_value=total_target_value,
            )
            site_score = (
                0 if current_anchor == harvester_position else 1,
                0 if committed_ring_position == ring_position else 1,
                0 if committed_direction == sentinel_direction else 1,
                0 if hits_core_center else 1,
                0 if best_target is not None and best_target.entity_type in TURRET_TYPES else 1,
                0 if best_target is not None and best_target.entity_type == EntityType.CORE else 1,
                -marginal_value,
                -uncovered_logistics_gain,
                0 if classification == RING_IMMEDIATE else 1,
                0 if friendly_ring_sentinels else 1,
                0 if not threatened else 1,
                turns_to_shot,
                -len(friendly_ring_sentinels),
                -_ring_frontness(
                    harvester_position=harvester_position,
                    ring_position=ring_position,
                    front_dx=front_dx,
                    front_dy=front_dy,
                ),
                manhattan(current_position, ring_position),
                -usable_sides,
                -immediate_open_sides,
                (direction_index - site_bias) % len(CARDINAL_DIRECTIONS),
                direction_index,
                ring_position.x + (ring_position.y * map_width),
            )
            ranked.append((site_score, site))
            _profile_bump(profile, "assault_sites_scored")

    ranked.sort(key=lambda item: item[0])
    if ranked:
        return [site for _, site in ranked]

    if (
        allow_exploratory_fallback
        and not friendly_ring_sentinels
    ):
        fallback = _fallback_anchor_site(
            harvester_position=harvester_position,
            map_width=map_width,
            map_height=map_height,
            grid=grid,
            my_team=my_team,
            actor_id=actor_id,
            blocked=blocked,
        )
        if fallback is not None:
            return [fallback]

    return []


def choose_best_site_for_harvester(
    *,
    harvester_position: Position,
    current_position: Position,
    enemies: list[VisibleEnemy],
    map_width: int,
    map_height: int,
    grid: dict[tuple[int, int], dict] | None = None,
    my_team=None,
    actor_id: int | None = None,
    blocked_ring_positions: set[Position] | None = None,
    legal_fire_fn=None,
    enemy_core_center: Position | None = None,
    current_anchor: Position | None = None,
    site_bias: int = 0,
    connected_friendly_conveyors=None,
    committed_ring_position: Position | None = None,
    committed_direction: Direction | None = None,
    allow_exploratory_fallback: bool = True,
    profile: dict | None = None,
) -> AssaultSite | None:
    _profile_bump(profile, "assault_choose_best_site_calls")
    ranked_sites = rank_assault_sites_for_harvester(
        harvester_position=harvester_position,
        current_position=current_position,
        enemies=enemies,
        map_width=map_width,
        map_height=map_height,
        grid=grid,
        my_team=my_team,
        actor_id=actor_id,
        blocked_ring_positions=blocked_ring_positions,
        legal_fire_fn=legal_fire_fn,
        enemy_core_center=enemy_core_center,
        current_anchor=current_anchor,
        site_bias=site_bias,
        connected_friendly_conveyors=connected_friendly_conveyors,
        committed_ring_position=committed_ring_position,
        committed_direction=committed_direction,
        allow_exploratory_fallback=allow_exploratory_fallback,
        profile=profile,
    )
    return ranked_sites[0] if ranked_sites else None


def assess_anchor(
    *,
    harvester_position: Position,
    current_position: Position | None = None,
    enemies: list[VisibleEnemy],
    grid: dict[tuple[int, int], dict] | None = None,
    my_team=None,
    actor_id: int | None = None,
    map_width: int | None = None,
    map_height: int | None = None,
    blocked_ring_positions: set[Position] | None = None,
    legal_fire_fn=None,
    enemy_core_center: Position | None = None,
    current_anchor: Position | None = None,
    site_bias: int = 0,
    connected_friendly_conveyors=None,
    friendly_builder_positions: list[tuple[int, Position]] | None = None,
    profile: dict | None = None,
) -> AnchorAssessment:
    _profile_bump(profile, "assault_assess_anchor_calls")
    cluster_positions = connected_enemy_logistics_cluster(
        harvester_position,
        enemies,
        profile=profile,
    )
    if not cluster_positions:
        cluster_positions = {harvester_position}

    enemy_logistics_count = sum(
        1
        for enemy in enemies
        if enemy.position in cluster_positions and enemy.position != harvester_position
    )
    adjacent_friendly_connected = _friendly_connected_neighbor_count(
        harvester_position,
        connected_friendly_conveyors,
    )
    pressure_established = False
    friendly_ring_sentinels, _ = _friendly_ring_sentinel_state(
        harvester_position,
        enemies=enemies,
        grid=grid,
        my_team=my_team,
    )
    anchor_visible_now = any(
        enemy.entity_type == EntityType.HARVESTER and enemy.position == harvester_position
        for enemy in enemies
    )
    pressure_established = bool(friendly_ring_sentinels) or adjacent_friendly_connected > 0

    ranked_sites: list[AssaultSite] = []
    if map_width is not None and map_height is not None:
        ranked_sites = rank_assault_sites_for_harvester(
            harvester_position=harvester_position,
            current_position=current_position or harvester_position,
            enemies=enemies,
            map_width=map_width,
            map_height=map_height,
            grid=grid,
            my_team=my_team,
            actor_id=actor_id,
            blocked_ring_positions=blocked_ring_positions,
            legal_fire_fn=legal_fire_fn,
            enemy_core_center=enemy_core_center,
            current_anchor=current_anchor,
            site_bias=site_bias,
            connected_friendly_conveyors=connected_friendly_conveyors,
            allow_exploratory_fallback=False,
            profile=profile,
        )

    useful_sites = len(ranked_sites)
    immediate_sites = sum(
        1 for site in ranked_sites if site.ring_classification == RING_IMMEDIATE
    )
    clearable_sites = sum(
        1 for site in ranked_sites if site.ring_classification == RING_CLEARABLE
    )
    best_marginal_value = ranked_sites[0].marginal_value if ranked_sites else 0
    sites_by_ring_position: dict[tuple[int, int], list[AssaultSite]] = {}
    for site in ranked_sites:
        sites_by_ring_position.setdefault(
            (site.ring_position.x, site.ring_position.y),
            [],
        ).append(site)

    useful_ring_sides = 0
    resolved_ring_sides = 0
    remaining_high_value_sites = 0
    best_logistics_gain = 0
    in_bounds_ring_sides = 0
    delegated_ring_positions: set[tuple[int, int]] = set()
    if friendly_builder_positions:
        for builder_id, builder_position in friendly_builder_positions:
            if actor_id is not None and builder_id == actor_id:
                continue
            for direction in CARDINAL_DIRECTIONS:
                ring_position = harvester_position.add(direction)
                if max(
                    abs(builder_position.x - ring_position.x),
                    abs(builder_position.y - ring_position.y),
                ) <= 1:
                    delegated_ring_positions.add((ring_position.x, ring_position.y))
    if map_width is not None and map_height is not None:
        for direction in CARDINAL_DIRECTIONS:
            ring_position = harvester_position.add(direction)
            ring_key = (ring_position.x, ring_position.y)
            if not is_in_bounds(ring_position, map_width, map_height):
                continue
            in_bounds_ring_sides += 1
            if ring_position in friendly_ring_sentinels:
                resolved_ring_sides += 1
                continue
            if ring_key in delegated_ring_positions:
                resolved_ring_sides += 1
                continue
            side_sites = sites_by_ring_position.get((ring_position.x, ring_position.y), [])
            best_side_site = side_sites[0] if side_sites else None
            if best_side_site is None:
                continue
            useful_ring_sides += 1
            remaining_high_value_sites += 1
            if best_side_site.ring_classification == RING_CLEARABLE:
                best_logistics_gain = max(best_logistics_gain, 1)

    if in_bounds_ring_sides <= 0 or resolved_ring_sides >= in_bounds_ring_sides:
        status = ANCHOR_SATURATED
    elif useful_ring_sides > 0:
        status = ANCHOR_LIVE
    elif pressure_established:
        status = ANCHOR_LIVE
    elif not anchor_visible_now:
        status = ANCHOR_LIVE
    else:
        status = ANCHOR_DRIED

    return AnchorAssessment(
        status=status,
        cluster_size=len(cluster_positions),
        enemy_logistics_count=enemy_logistics_count,
        adjacent_friendly_connected=adjacent_friendly_connected,
        friendly_ring_sentinels=len(friendly_ring_sentinels),
        pressure_established=pressure_established,
        anchor_visible_now=anchor_visible_now,
        useful_ring_sides=useful_ring_sides,
        resolved_ring_sides=resolved_ring_sides,
        remaining_high_value_sites=remaining_high_value_sites,
        best_logistics_gain=best_logistics_gain,
        useful_sites=useful_sites,
        immediate_sites=immediate_sites,
        clearable_sites=clearable_sites,
        best_marginal_value=best_marginal_value,
    )


def choose_best_visible_assault_site(
    *,
    current_position: Position,
    enemies: list[VisibleEnemy],
    map_width: int,
    map_height: int,
    grid: dict[tuple[int, int], dict],
    my_team,
    actor_id: int | None = None,
    blocked_ring_positions: set[Position] | None = None,
    legal_fire_fn=None,
    enemy_core_center: Position | None = None,
    current_anchor: Position | None = None,
    site_bias: int = 0,
    connected_friendly_conveyors=None,
    ignored_harvesters: set[Position] | None = None,
    committed_ring_position: Position | None = None,
    committed_direction: Direction | None = None,
    profile: dict | None = None,
    core_rusher_anchor: Position | None = None,
) -> AssaultSite | None:
    """Return the best visible assault site for a builder.

    `core_rusher_anchor`, if provided, switches the score tuple into
    "rusher" mode: sites whose ring position is closer to the anchor
    (typically the enemy core derived from world symmetry) receive a
    higher rank. This lets the cardinal-W rusher bias toward sites that
    threaten the enemy core without disturbing the generic harvester
    hunting used by the diagonal opening assault builders.
    """
    best: tuple[tuple[int, ...], AssaultSite] | None = None
    ignored_harvesters = ignored_harvesters or set()
    core_rusher_mode = core_rusher_anchor is not None

    for enemy in enemies:
        if enemy.entity_type != EntityType.HARVESTER:
            continue
        if enemy.position in ignored_harvesters:
            continue
        _profile_bump(profile, "assault_visible_harvesters_considered")
        site = choose_best_site_for_harvester(
            harvester_position=enemy.position,
            current_position=current_position,
            enemies=enemies,
            map_width=map_width,
            map_height=map_height,
            grid=grid,
            my_team=my_team,
            actor_id=actor_id,
            blocked_ring_positions=blocked_ring_positions,
            legal_fire_fn=legal_fire_fn,
            enemy_core_center=enemy_core_center,
            current_anchor=current_anchor,
            site_bias=site_bias,
            connected_friendly_conveyors=connected_friendly_conveyors,
            committed_ring_position=committed_ring_position,
            committed_direction=committed_direction,
            profile=profile,
        )
        if site is None:
            continue
        surround_progress, _covered_targets = _friendly_ring_sentinel_state(
            enemy.position,
            enemies=enemies,
            grid=grid,
            my_team=my_team,
        )
        if core_rusher_mode:
            # Rusher score: SAME shape as the generic score, but with
            # a core-distance TIEBREAKER inserted AFTER the strategic
            # primaries (commit stickiness, surround progress, useful
            # shot timing, threatened-site avoidance, reachability).
            # An earlier version put `core_dist` as the LEADING sort
            # key, which lexicographically dominated and caused the
            # rusher to commit to far-from-self, unreachable,
            # threatened, or slow-to-fire sites just because their
            # ring happened to be a few tiles closer to the enemy
            # core anchor. Keeping the primaries intact and inserting
            # `core_dist` as a nudge between `manhattan` (reachability
            # proxy) and `-site.usable_sides` preserves winnable-site
            # preference while still biasing among equally-good sites
            # toward the enemy core anchor.
            core_dist = site.ring_position.distance_squared(core_rusher_anchor)
            score = (
                0 if current_anchor == enemy.position else 1,
                0 if surround_progress else 1,
                -len(surround_progress),
                site.turns_to_useful_shot,
                0 if not site.threatened else 1,
                manhattan(current_position, site.ring_position),
                core_dist,
                -site.usable_sides,
                -site.immediate_open_sides,
                enemy.position.x + (enemy.position.y * map_width),
            )
        else:
            score = (
                0 if current_anchor == enemy.position else 1,
                0 if surround_progress else 1,
                -len(surround_progress),
                site.turns_to_useful_shot,
                0 if not site.threatened else 1,
                manhattan(current_position, site.ring_position),
                -site.usable_sides,
                -site.immediate_open_sides,
                enemy.position.x + (enemy.position.y * map_width),
            )
        if best is None or score < best[0]:
            best = (score, site)

    return None if best is None else best[1]


def choose_best_assault_site(
    *,
    current_position: Position,
    enemies: list[VisibleEnemy],
    map_width: int,
    map_height: int,
    blocked_ring_positions: set[Position] | None = None,
    legal_fire_fn=None,
    enemy_core_center: Position | None = None,
) -> AssaultSite | None:
    best: tuple[tuple[int, ...], AssaultSite] | None = None
    for enemy in enemies:
        if enemy.entity_type != EntityType.HARVESTER:
            continue
        site = choose_best_site_for_harvester(
            harvester_position=enemy.position,
            current_position=current_position,
            enemies=enemies,
            map_width=map_width,
            map_height=map_height,
            blocked_ring_positions=blocked_ring_positions,
            legal_fire_fn=legal_fire_fn,
            enemy_core_center=enemy_core_center,
        )
        if site is None:
            continue
        score = (
            0 if site.target.entity_type in TURRET_TYPES else 1,
            0 if site.hits_core_center else 1,
            -site.uncovered_logistics_gain,
            site.turns_to_useful_shot,
            manhattan(current_position, site.ring_position),
            -site.cluster_size,
            enemy.position.x + (enemy.position.y * map_width),
        )
        if best is None or score < best[0]:
            best = (score, site)
    return None if best is None else best[1]


def _better_predicted_candidate(
    a: tuple[Position, str, str | None],
    b: tuple[Position, str, str | None],
    *,
    best_mode: str | None,
) -> tuple[Position, str, str | None]:
    a_rank = SOURCE_RANK[a[1]]
    b_rank = SOURCE_RANK[b[1]]
    if a_rank != b_rank:
        return a if a_rank < b_rank else b
    a_mode_rank = 0 if a[2] == best_mode else 1
    b_mode_rank = 0 if b[2] == best_mode else 1
    if a_mode_rank != b_mode_rank:
        return a if a_mode_rank < b_mode_rank else b
    return min(a, b, key=lambda item: (item[0].x, item[0].y))


def build_predicted_enemy_harvesters(
    *,
    current_position: Position,
    grid: dict[tuple[int, int], dict],
    map_width: int,
    map_height: int,
    my_team,
    surviving_modes: tuple[str, ...],
    best_mode: str | None,
    enemy_core_anchor: Position | None,
    remembered_ores: set[Position],
    confirmed_enemy_harvesters: set[Position],
    current_anchor: Position | None = None,
) -> list[PredictedHarvester]:
    raw_candidates: list[tuple[Position, str, str | None]] = [
        (position, "CONFIRMED", None) for position in confirmed_enemy_harvesters
    ]

    for ore_pos in remembered_ores:
        for mode in surviving_modes:
            raw_candidates.append(
                (
                    mirror_position(
                        ore_pos, mode, map_width=map_width, map_height=map_height
                    ),
                    "MIRRORED_ORE",
                    mode,
                )
            )

    deduped: list[tuple[Position, str, str | None]] = []
    for candidate in raw_candidates:
        merged = False
        for index, current in enumerate(deduped):
            if manhattan(candidate[0], current[0]) <= 2:
                deduped[index] = _better_predicted_candidate(
                    current, candidate, best_mode=best_mode
                )
                merged = True
                break
        if not merged:
            deduped.append(candidate)

    predicted = []
    for position, source, mode in deduped:
        immediate_open_sides, clearable_sides, unseen_sides = _ring_side_counts(
            harvester_position=position,
            grid=grid,
            map_width=map_width,
            map_height=map_height,
            my_team=my_team,
            actor_id=None,
        )
        # For scouting, an entirely unseen ring is still actionable: we need a
        # candidate to walk toward before we can classify it precisely.
        usable_sides = immediate_open_sides + clearable_sides + unseen_sides
        if usable_sides <= 0:
            continue
        distance_to_anchor = (
            manhattan(position, enemy_core_anchor)
            if enemy_core_anchor is not None
            else 9999
        )
        predicted.append(
            PredictedHarvester(
                position=position,
                source=source,
                source_rank=SOURCE_RANK[source],
                usable_sides=usable_sides,
                immediate_open_sides=immediate_open_sides,
                clearable_sides=clearable_sides,
                unseen_sides=unseen_sides,
                travel_distance=manhattan(current_position, position),
                distance_to_core_anchor=distance_to_anchor,
                same_lane=(
                    current_anchor is not None
                    and (
                        manhattan(current_anchor, position) <= 4
                        or current_anchor.x == position.x
                        or current_anchor.y == position.y
                    )
                ),
                mode=mode,
            )
        )

    predicted.sort(
        key=lambda candidate: (
            candidate.source_rank,
            0 if candidate.same_lane else 1,
            -candidate.distance_to_core_anchor,
            -candidate.usable_sides,
            -candidate.immediate_open_sides,
            -candidate.unseen_sides,
            0 if candidate.mode == best_mode else 1,
            candidate.travel_distance,
            candidate.distance_to_core_anchor,
            candidate.position.x,
            candidate.position.y,
        )
    )
    return predicted[:6]


def choose_ring_builder_id(
    friendly_builders: list[tuple[int, Position]],
    *,
    target_ring_tile: Position,
    anchor: Position | None = None,
) -> int | None:
    if not friendly_builders:
        return None

    eligible = []
    seen_ids = set()
    for builder_id, position in friendly_builders:
        if builder_id in seen_ids:
            continue
        seen_ids.add(builder_id)
        if anchor is not None and manhattan(position, anchor) > 10:
            continue
        eligible.append((builder_id, position))

    if not eligible:
        eligible = friendly_builders

    builder_id, _ = min(
        eligible,
        key=lambda item: (
            manhattan(item[1], target_ring_tile),
            item[0],
        ),
    )
    return builder_id
