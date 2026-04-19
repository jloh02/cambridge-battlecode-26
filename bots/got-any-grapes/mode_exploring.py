from cambc import Controller, EntityType, Environment, Position
import time
import navigation
import perception
import marker
import utils
from states import BuilderMode

EXPLORE_CLAIM_PENALTY = 8
# Per-ally closer penalty. Previously a prohibitive 1000, which on
# crowded small maps (e.g. default_small1 with 11 builders piled near
# the 4x4 chunk grid) made every chunk score >= 1000 and degenerated
# slot selection to "least bad" random. A small deconfliction penalty
# still spreads builders whose chunks overlap but does not pin every
# builder onto the same "least bad" chunk when the map is tightly
# packed.
EXPLORE_ALLY_CLOSER_PENALTY = 5
EXPLORE_STUCK_RETRY_TURNS = 4
EXPLORE_EXHAUSTED_RESET_INTERVAL = 60


def _ensure_chunks_initialized(bot, map_width: int, map_height: int):
    """Initializes map chunks and the unreachable blacklist."""
    if bot.all_map_chunks is None:
        chunk_cols = (map_width + perception.CHUNK_SIZE - 1) // perception.CHUNK_SIZE
        chunk_rows = (map_height + perception.CHUNK_SIZE - 1) // perception.CHUNK_SIZE
        bot.all_map_chunks = [
            (cx, cy) for cx in range(chunk_cols) for cy in range(chunk_rows)
        ]

    # Initialize the blacklist if it doesn't exist
    if not hasattr(bot, "unreachable_chunks"):
        bot.unreachable_chunks = set()

    # Keep a short grace window before abandoning an exploration target.
    if not hasattr(bot, "explore_stuck_turns"):
        bot.explore_stuck_turns = 0


def _get_chunk_center(
    chunk: tuple[int, int], map_width: int, map_height: int
) -> Position:
    return Position(
        min(
            map_width - 1, chunk[0] * perception.CHUNK_SIZE + perception.CHUNK_SIZE // 2
        ),
        min(
            map_height - 1,
            chunk[1] * perception.CHUNK_SIZE + perception.CHUNK_SIZE // 2,
        ),
    )


def _chunk_bounds(
    chunk: tuple[int, int],
    map_width: int,
    map_height: int,
) -> tuple[int, int, int, int]:
    min_x = chunk[0] * perception.CHUNK_SIZE
    min_y = chunk[1] * perception.CHUNK_SIZE
    max_x = min(map_width - 1, min_x + perception.CHUNK_SIZE - 1)
    max_y = min(map_height - 1, min_y + perception.CHUNK_SIZE - 1)
    return min_x, min_y, max_x, max_y


def _is_viable_explore_target_tile(bot, ct: Controller, pos: Position) -> bool:
    if not utils.in_bounds(ct, pos):
        return False

    tile_data = bot.grid.get((pos.x, pos.y))
    if tile_data is None or tile_data.get("env") is None:
        return True

    if tile_data.get("env") != Environment.EMPTY:
        return False

    entity = tile_data.get("entity")
    entity_team = tile_data.get("entity_team")
    if entity == EntityType.BUILDER_BOT and pos != ct.get_position():
        return False
    if entity is not None and entity not in {EntityType.BUILDER_BOT}:
        return False

    building = tile_data.get("building")
    building_team = tile_data.get("building_team")
    if building is None or building in {
        EntityType.ROAD,
        EntityType.CONVEYOR,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.MARKER,
    }:
        return True
    return building == EntityType.CORE and building_team == ct.get_team()


def _get_chunk_target(
    bot,
    ct: Controller,
    chunk: tuple[int, int],
    map_width: int,
    map_height: int,
) -> Position | None:
    center = _get_chunk_center(chunk, map_width, map_height)
    if _is_viable_explore_target_tile(bot, ct, center):
        return center

    current_pos = ct.get_position()
    min_x, min_y, max_x, max_y = _chunk_bounds(chunk, map_width, map_height)
    best: tuple[tuple[int, int, int, int], Position] | None = None
    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            candidate = Position(x, y)
            if not _is_viable_explore_target_tile(bot, ct, candidate):
                continue
            score = (
                abs(candidate.x - center.x) + abs(candidate.y - center.y),
                utils.manhattan(current_pos, candidate),
                candidate.x,
                candidate.y,
            )
            if best is None or score < best[0]:
                best = (score, candidate)
    return None if best is None else best[1]


def _clear_reached_target(bot) -> bool:
    """Clears the exploration target if the bot has explored it."""
    if (
        bot.explore_target_chunk is not None
        and bot.explore_target_chunk in bot.explored_tiles
    ):
        bot.explore_target_chunk = None
        bot.explore_target_pos = None
        bot.explore_stuck_turns = 0
        return True
    return False


def _select_optimal_unexplored_chunk(
    bot, ct: Controller, current_chunk: tuple[int, int]
):
    """Selects a chunk using dynamic scoring for deconflicting and blacklisting."""
    valid_chunks = [
        c
        for c in bot.all_map_chunks
        if c not in bot.explored_tiles and c not in bot.unreachable_chunks
    ]

    if not valid_chunks:
        bot.explore_target_chunk = None
        return

    current_pos = ct.get_position()
    core_chunk = (
        bot.core_pos.x // perception.CHUNK_SIZE,
        bot.core_pos.y // perception.CHUNK_SIZE,
    )
    # Use unit ID to create a deterministic but builder-specific tie-break.
    # This helps equal-distance explorers fan out without any shared state.
    id_hash = ct.get_id() & 0xFF
    claimed_chunks = getattr(bot, "claimed_explore_chunks", set())

    best_chunk = None
    best_score = float("inf")
    current_pos_tuple = (current_pos.x, current_pos.y)

    for chunk in valid_chunks:
        # 1. Base Cost: Manhattan distance in chunk space
        dist_to_me = abs(chunk[0] - current_chunk[0]) + abs(chunk[1] - current_chunk[1])
        score = dist_to_me
        if chunk in claimed_chunks:
            score += EXPLORE_CLAIM_PENALTY

        # 2. Deconflict: Penalize if allies are closer to this chunk
        for ally_pos in bot.bot_locations:
            if ally_pos == current_pos_tuple:
                continue

            ally_chunk = (
                ally_pos[0] // perception.CHUNK_SIZE,
                ally_pos[1] // perception.CHUNK_SIZE,
            )
            dist_ally_to_chunk = abs(chunk[0] - ally_chunk[0]) + abs(
                chunk[1] - ally_chunk[1]
            )

            # If an ally is closer to this target, add a massive penalty
            if dist_ally_to_chunk < dist_to_me:
                score += EXPLORE_ALLY_CLOSER_PENALTY

        # 3. Tie-breaker: Prefer chunks closer to the core, with builder-specific
        # offset to break symmetry when multiple builders evaluate the same chunks.
        dist_to_core = abs(chunk[0] - core_chunk[0]) + abs(chunk[1] - core_chunk[1])
        score += dist_to_core * 0.1
        # Deterministic per-builder spread hash. Previously a 0.001
        # multiplier left this as a cosmetic perturbation; on small
        # crowded maps that allowed multiple builders to lock on the
        # same lowest-manhattan chunk and ignore the rest of the map.
        # A 0.02 multiplier shifts the score by up to ~5 across the
        # 0xFF range. Large enough to break symmetry within a tight
        # manhattan tie (same chunk distance within 4 tiles) but small
        # enough to avoid displacing builders toward objectively much
        # farther chunks.
        spread_hash = (
            (chunk[0] * 73_856_093)
            ^ (chunk[1] * 19_349_663)
            ^ (id_hash * 83_492_791)
        ) & 0xFF
        score += spread_hash * 0.02

        if score < best_score:
            best_score = score
            best_chunk = chunk

    # If all valid chunks are heavily penalized (score > 1000),
    # the bot will still pick the "least bad" one, ensuring it doesn't just freeze.
    bot.explore_target_chunk = best_chunk


def execute(bot, ct: Controller):
    profile_enabled = utils.DEBUG_TURN_PROFILE

    phase_start = time.time_ns() if profile_enabled else 0
    map_width = ct.get_map_width()
    map_height = ct.get_map_height()
    current_pos = ct.get_position()
    current_chunk = (
        current_pos.x // perception.CHUNK_SIZE,
        current_pos.y // perception.CHUNK_SIZE,
    )

    _ensure_chunks_initialized(bot, map_width, map_height)
    if profile_enabled:
        utils.bump_profile(bot, "explore_setup_ns", time.time_ns() - phase_start)

    # 1. Clear target if reached
    phase_start = time.time_ns() if profile_enabled else 0
    if _clear_reached_target(bot):
        # Only switch to FINDING_ORE if we actually know about ore.
        # Previously we always switched, causing a wasted turn when the
        # chunk had no ore: FINDING_ORE → no target → back to EXPLORING.
        if bot.titanium_locations or bot.axionite_locations:
            bot.builder_mode = BuilderMode.FINDING_ORE
            if profile_enabled:
                utils.bump_profile(bot, "explore_clear_target_ns", time.time_ns() - phase_start)
            return
        # Otherwise stay in EXPLORING and pick the next chunk below.
    if profile_enabled:
        utils.bump_profile(bot, "explore_clear_target_ns", time.time_ns() - phase_start)

    # 2. Assign new target if needed
    if bot.explore_target_chunk is None:
        phase_start = time.time_ns() if profile_enabled else 0
        while True:
            _select_optimal_unexplored_chunk(bot, ct, current_chunk)
            if bot.explore_target_chunk is None:
                break
            bot.explore_target_pos = _get_chunk_target(
                bot,
                ct,
                bot.explore_target_chunk,
                map_width,
                map_height,
            )
            if bot.explore_target_pos is not None:
                break
            bot.unreachable_chunks.add(bot.explore_target_chunk)
            bot.explore_target_chunk = None
        if bot.explore_target_chunk is not None:
            bot.explore_stuck_turns = 0
            if profile_enabled:
                utils.bump_profile(bot, "explore_select_target_ns", time.time_ns() - phase_start)
        else:
            # All chunks explored or blacklisted — periodically reset the
            # unreachable blacklist so the builder can retry after the map
            # state has changed (friendly buildings may open new paths).
            last_reset = getattr(bot, "explore_exhausted_last_reset", -9999)
            if ct.get_current_round() - last_reset >= EXPLORE_EXHAUSTED_RESET_INTERVAL:
                bot.unreachable_chunks = set()
                bot.explore_exhausted_last_reset = ct.get_current_round()
                if utils.DEBUG:
                    bot.logger.log("exploration exhausted: resetting unreachable blacklist")
            bot.builder_mode = BuilderMode.FINDING_ORE
            if profile_enabled:
                utils.bump_profile(bot, "explore_select_target_ns", time.time_ns() - phase_start)
            return

    # 3. Execute Movement and Catch A* Failures
    if bot.explore_target_pos is not None:
        if utils.DEBUG:
            bot.logger.log(
                f"Exploring towards chunk {bot.explore_target_chunk} at {bot.explore_target_pos}"
            )

        phase_start = time.time_ns() if profile_enabled else 0
        path_found = navigation.move_towards(bot, ct, bot.explore_target_pos)
        if profile_enabled:
            utils.bump_profile(bot, "explore_nav_ns", time.time_ns() - phase_start)

        phase_start = time.time_ns() if profile_enabled else 0
        progress_made = path_found and not navigation.consume_shared_progress_stall(bot)

        if progress_made:
            bot.explore_stuck_turns = 0
            if profile_enabled:
                utils.bump_profile(bot, "explore_progress_note_ns", time.time_ns() - phase_start)
            return

        bot.explore_stuck_turns += 1
        if utils.DEBUG:
            bot.logger.log(
                f"Exploration stalled for target {bot.explore_target_chunk} "
                f"({bot.explore_stuck_turns}/{EXPLORE_STUCK_RETRY_TURNS})."
            )

        if bot.explore_stuck_turns < EXPLORE_STUCK_RETRY_TURNS:
            if profile_enabled:
                utils.bump_profile(bot, "explore_progress_note_ns", time.time_ns() - phase_start)
            return
        if profile_enabled:
            utils.bump_profile(bot, "explore_progress_note_ns", time.time_ns() - phase_start)

        phase_start = time.time_ns() if profile_enabled else 0
        replacement_target = _get_chunk_target(
            bot,
            ct,
            bot.explore_target_chunk,
            map_width,
            map_height,
        )
        if (
            replacement_target is not None
            and replacement_target != bot.explore_target_pos
        ):
            if utils.DEBUG:
                bot.logger.log(
                    f"Retargeting within chunk {bot.explore_target_chunk} "
                    f"from {bot.explore_target_pos} to {replacement_target}"
            )
            bot.explore_target_pos = replacement_target
            bot.explore_stuck_turns = 0
            if profile_enabled:
                utils.bump_profile(bot, "explore_retarget_ns", time.time_ns() - phase_start)
            return

        if utils.DEBUG:
            bot.logger.log(
                f"Target {bot.explore_target_chunk} deemed unreachable after retries. Blacklisting."
            )
        bot.unreachable_chunks.add(bot.explore_target_chunk)
        bot.explore_target_chunk = None
        bot.explore_target_pos = None
        bot.explore_stuck_turns = 0
        if profile_enabled:
            utils.bump_profile(bot, "explore_retarget_ns", time.time_ns() - phase_start)
