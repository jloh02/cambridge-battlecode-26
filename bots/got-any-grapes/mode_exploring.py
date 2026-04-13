from cambc import Controller, Position
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
    map_width = ct.get_map_width()
    map_height = ct.get_map_height()
    current_pos = ct.get_position()
    current_chunk = (
        current_pos.x // perception.CHUNK_SIZE,
        current_pos.y // perception.CHUNK_SIZE,
    )

    _ensure_chunks_initialized(bot, map_width, map_height)

    # 1. Clear target if reached
    if _clear_reached_target(bot):
        bot.builder_mode = BuilderMode.FINDING_ORE
        return

    # 2. Assign new target if needed
    if bot.explore_target_chunk is None:
        _select_optimal_unexplored_chunk(bot, ct, current_chunk)
        if bot.explore_target_chunk is not None:
            bot.explore_target_pos = _get_chunk_center(
                bot.explore_target_chunk, map_width, map_height
            )
            bot.explore_stuck_turns = 0
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
            return

    # 3. Execute Movement and Catch A* Failures
    if bot.explore_target_pos is not None:
        if utils.DEBUG:
            bot.logger.log(
                f"Exploring towards chunk {bot.explore_target_chunk} at {bot.explore_target_pos}"
            )

        path_found = navigation.move_towards(bot, ct, bot.explore_target_pos)
        progress_made = path_found and not navigation.consume_shared_progress_stall(bot)

        if progress_made:
            bot.explore_stuck_turns = 0
            return

        bot.explore_stuck_turns += 1
        if utils.DEBUG:
            bot.logger.log(
                f"Exploration stalled for target {bot.explore_target_chunk} "
                f"({bot.explore_stuck_turns}/{EXPLORE_STUCK_RETRY_TURNS})."
            )

        if bot.explore_stuck_turns < EXPLORE_STUCK_RETRY_TURNS:
            return

        if utils.DEBUG:
            bot.logger.log(
                f"Target {bot.explore_target_chunk} deemed unreachable after retries. Blacklisting."
            )
        bot.unreachable_chunks.add(bot.explore_target_chunk)
        bot.explore_target_chunk = None
        bot.explore_target_pos = None
        bot.explore_stuck_turns = 0
