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
    EntityType.ARMOURED_CONVEYOR,
}
HARASSABLE_PASSABLE_BUILDINGS = {
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
}
TURRET_TYPES = {
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.LAUNCHER,
}
THREATENING_TYPES = TURRET_TYPES | {EntityType.BUILDER_BOT}
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
SLOT_DIAGONALS = {
    0: Direction.NORTHEAST,
    1: Direction.NORTHWEST,
    2: Direction.SOUTHEAST,
    3: Direction.SOUTHWEST,
}
LEFT_PERPENDICULAR = {
    0: Direction.NORTHWEST,
    1: Direction.SOUTHWEST,
    2: Direction.NORTHEAST,
    3: Direction.SOUTHEAST,
}
RIGHT_PERPENDICULAR = {
    0: Direction.SOUTHEAST,
    1: Direction.NORTHEAST,
    2: Direction.SOUTHWEST,
    3: Direction.NORTHWEST,
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
    cluster_size: int
    usable_sides: int
    immediate_open_sides: int
    turns_to_useful_shot: int
    threatened: bool
    ring_classification: str


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


def evaluate_symmetry_modes(
    *,
    grid: dict[tuple[int, int], dict],
    map_width: int,
    map_height: int,
    core_pos: Position | None,
    previous_modes: tuple[str, ...] = SYMMETRY_MODES,
    max_samples: int = 128,
) -> tuple[tuple[str, ...], str | None, str, tuple[SymmetryModeScore, ...]]:
    if core_pos is None:
        return previous_modes, None, "LOW", ()

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
    samples = informative_tiles[:max_samples]

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


def sentinel_attack_tiles(
    origin: Position,
    direction: Direction,
    *,
    max_range_sq: int = 32,
) -> set[Position]:
    attackable: set[Position] = set()
    dx, dy = STEP_BY_DIRECTION[direction]
    for step in range(1, 7):
        base = Position(origin.x + (dx * step), origin.y + (dy * step))
        if distance_sq(base, origin) > max_range_sq:
            break
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                candidate = Position(base.x + ox, base.y + oy)
                rel_x = candidate.x - origin.x
                rel_y = candidate.y - origin.y
                if rel_x == 0 and rel_y == 0:
                    continue
                if rel_x * dx + rel_y * dy <= 0:
                    continue
                if distance_sq(candidate, origin) > max_range_sq:
                    continue
                attackable.add(candidate)
    return attackable


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
) -> set[Position]:
    logistics_positions = {
        enemy.position
        for enemy in enemies
        if enemy.entity_type in CONNECTED_LOGISTICS_TYPES
    }
    if anchor_harvester not in logistics_positions:
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


def connected_friendly_harvesters(
    *,
    grid: dict[tuple[int, int], dict],
    my_team,
    connected_conveyors,
) -> set[Position]:
    connected_harvesters = set()
    conveyor_keys = set(connected_conveyors)
    if not conveyor_keys:
        return connected_harvesters

    for key, data in grid.items():
        if data.get("building") == EntityType.HARVESTER and data.get("building_team") == my_team:
            harvester_pos = Position(key[0], key[1])
        elif data.get("entity") == EntityType.HARVESTER and data.get("entity_team") == my_team:
            harvester_pos = Position(key[0], key[1])
        else:
            continue

        for direction in CARDINAL_DIRECTIONS:
            neighbor = harvester_pos.add(direction)
            if (neighbor.x, neighbor.y) in conveyor_keys:
                connected_harvesters.add(harvester_pos)
                break
    return connected_harvesters


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
) -> Position | None:
    visible_candidates = []
    seen_visible = set()
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

    visible_keys = set(seen_visible)
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
) -> int | None:
    if enemy.entity_type in TURRET_TYPES:
        return 0
    if enemy.position == anchor_harvester:
        return None
    if enemy.position in cluster_positions:
        return 1
    if enemy.entity_type == EntityType.CORE:
        return 2
    return None


def _best_target_for_site(
    *,
    harvester_position: Position,
    ring_position: Position,
    sentinel_direction: Direction,
    enemies: list[VisibleEnemy],
    cluster_positions: set[Position],
    map_width: int,
    legal_fire_fn=None,
) -> SiteTarget | None:
    attack_tiles = sentinel_attack_tiles(ring_position, sentinel_direction)
    best_target: tuple[tuple[int, int, int, int], SiteTarget] | None = None
    for enemy in enemies:
        if enemy.position not in attack_tiles:
            continue
        priority = _target_priority(
            enemy,
            anchor_harvester=harvester_position,
            cluster_positions=cluster_positions,
        )
        if priority is None:
            continue
        if legal_fire_fn is not None and not legal_fire_fn(
            ring_position, sentinel_direction, enemy.position
        ):
            continue
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
    return None if best_target is None else best_target[1]


def visible_threat_score(
    *,
    ring_position: Position,
    enemies: list[VisibleEnemy],
) -> int:
    threat = 0
    for enemy in enemies:
        if enemy.entity_type in TURRET_TYPES:
            if enemy.direction is not None:
                if ring_position in sentinel_attack_tiles(enemy.position, enemy.direction):
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
    current_anchor: Position | None = None,
    site_bias: int = 0,
) -> AssaultSite | None:
    blocked = blocked_ring_positions or set()
    cluster_positions = connected_enemy_logistics_cluster(harvester_position, enemies)
    if not cluster_positions:
        cluster_positions = {harvester_position}

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
    best: tuple[tuple[int, ...], AssaultSite] | None = None

    for direction_index, site_direction in enumerate(CARDINAL_DIRECTIONS):
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

        for sentinel_direction in ALL_EIGHT_DIRECTIONS:
            if not can_feed_sentinel(
                harvester_position, ring_position, sentinel_direction
            ):
                continue
            target = _best_target_for_site(
                harvester_position=harvester_position,
                ring_position=ring_position,
                sentinel_direction=sentinel_direction,
                enemies=enemies,
                cluster_positions=cluster_positions,
                map_width=map_width,
                legal_fire_fn=legal_fire_fn,
            )
            if target is None:
                continue

            threat_score = visible_threat_score(
                ring_position=ring_position,
                enemies=enemies,
            )
            threatened = threat_score > 0
            if threatened and not (
                classification == RING_IMMEDIATE
                and target.entity_type in TURRET_TYPES
            ):
                continue

            turns_to_shot = 0 if classification == RING_IMMEDIATE else 1
            site = AssaultSite(
                harvester_position=harvester_position,
                ring_position=ring_position,
                sentinel_direction=sentinel_direction,
                target=target,
                cluster_size=len(cluster_positions),
                usable_sides=usable_sides,
                immediate_open_sides=immediate_open_sides,
                turns_to_useful_shot=turns_to_shot,
                threatened=threatened,
                ring_classification=classification,
            )
            site_score = (
                0 if current_anchor == harvester_position else 1,
                0 if not threatened else 1,
                turns_to_shot,
                manhattan(current_position, ring_position),
                -len(cluster_positions),
                -usable_sides,
                -immediate_open_sides,
                (direction_index - site_bias) % len(CARDINAL_DIRECTIONS),
                direction_index,
                ring_position.x + (ring_position.y * map_width),
            )
            if best is None or site_score < best[0]:
                best = (site_score, site)

    if best is not None:
        return best[1]

    if usable_sides <= 0:
        return None

    for direction in CARDINAL_DIRECTIONS:
        ring_position = harvester_position.add(direction)
        if ring_position in blocked:
            continue
        if not is_in_bounds(ring_position, map_width, map_height):
            continue
        if grid is None or my_team is None:
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
                    cluster_size=len(cluster_positions),
                    usable_sides=usable_sides,
                    immediate_open_sides=immediate_open_sides,
                    turns_to_useful_shot=1 if classification == RING_CLEARABLE else 0,
                    threatened=False,
                    ring_classification=classification,
                )
    return None


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
    current_anchor: Position | None = None,
    site_bias: int = 0,
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
            grid=grid,
            my_team=my_team,
            actor_id=actor_id,
            blocked_ring_positions=blocked_ring_positions,
            legal_fire_fn=legal_fire_fn,
            current_anchor=current_anchor,
            site_bias=site_bias,
        )
        if site is None:
            continue
        score = (
            0 if current_anchor == enemy.position else 1,
            0 if not site.threatened else 1,
            site.turns_to_useful_shot,
            manhattan(current_position, site.ring_position),
            -site.cluster_size,
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
        )
        if site is None:
            continue
        score = (
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
    connected_friendly_harvesters: set[Position],
    remembered_ores: set[Position],
    confirmed_enemy_harvesters: set[Position],
    current_anchor: Position | None = None,
) -> list[PredictedHarvester]:
    raw_candidates: list[tuple[Position, str, str | None]] = [
        (position, "CONFIRMED", None) for position in confirmed_enemy_harvesters
    ]

    for harvester in connected_friendly_harvesters:
        for mode in surviving_modes:
            raw_candidates.append(
                (
                    mirror_position(
                        harvester, mode, map_width=map_width, map_height=map_height
                    ),
                    "MIRRORED_FRIENDLY_HARVESTER",
                    mode,
                )
            )

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
        usable_sides = immediate_open_sides + clearable_sides
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


def choose_support_harassment_target(
    *,
    anchor: Position,
    enemies: list[VisibleEnemy],
    current_position: Position,
) -> Position | None:
    cluster = connected_enemy_logistics_cluster(anchor, enemies)
    if not cluster:
        return None

    candidates = []
    for enemy in enemies:
        if enemy.position not in cluster:
            continue
        if enemy.entity_type not in HARASSABLE_PASSABLE_BUILDINGS:
            continue
        candidates.append(enemy.position)

    if not candidates:
        return None
    return min(
        candidates,
        key=lambda position: (
            manhattan(current_position, position),
            manhattan(anchor, position),
            position.x,
            position.y,
        ),
    )


def spread_sweep_target(
    *,
    anchor: Position,
    spawn_slot: int | None,
    map_width: int,
    map_height: int,
    recently_visited: set[tuple[int, int]] | None = None,
    blocked_positions: set[tuple[int, int]] | None = None,
) -> Position:
    slot = 0 if spawn_slot is None else spawn_slot
    recently_visited = recently_visited or set()
    blocked_positions = blocked_positions or set()

    def _step(position: Position, direction: Direction, steps: int) -> Position:
        dx, dy = STEP_BY_DIRECTION[direction]
        return Position(position.x + (dx * steps), position.y + (dy * steps))

    candidates = [
        _step(anchor, SLOT_DIAGONALS.get(slot, Direction.NORTHEAST), 3),
        _step(anchor, SLOT_DIAGONALS.get(slot, Direction.NORTHEAST), 2),
        anchor,
        _step(anchor, LEFT_PERPENDICULAR.get(slot, Direction.NORTHWEST), 3),
        _step(anchor, RIGHT_PERPENDICULAR.get(slot, Direction.SOUTHEAST), 3),
    ]

    ordered_candidates = []
    seen = set()
    for candidate in candidates:
        clamped = Position(
            min(max(candidate.x, 0), map_width - 1),
            min(max(candidate.y, 0), map_height - 1),
        )
        key = (clamped.x, clamped.y)
        if key in seen:
            continue
        seen.add(key)
        ordered_candidates.append(clamped)

    for candidate in ordered_candidates:
        key = (candidate.x, candidate.y)
        if key in blocked_positions or key in recently_visited:
            continue
        return candidate

    for candidate in ordered_candidates:
        key = (candidate.x, candidate.y)
        if key in blocked_positions:
            continue
        return candidate

    for candidate in ordered_candidates:
        key = (candidate.x, candidate.y)
        if key not in recently_visited:
            return candidate

    return ordered_candidates[0]
