from cambc import Controller, Position
import navigation
import perception
import marker
import utils
from states import BuilderMode

EXPLORE_CLAIM_PENALTY = 0
EXPLORE_ALLY_CLOSER_PENALTY = 3
EXPLORE_STUCK_RETRY_TURNS = 4


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

    best_chunk = None
    best_score = float("inf")

    for chunk in valid_chunks:
        # 1. Base Cost: Manhattan distance in chunk space
        dist_to_me = abs(chunk[0] - current_chunk[0]) + abs(chunk[1] - current_chunk[1])
        score = dist_to_me

        # 2. Deconflict: Penalize if allies are closer to this chunk
        for ally_pos in bot.bot_locations:
            if ally_pos == current_pos:
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
                score += 1000

        # 3. Tie-breaker: Prefer chunks closer to the core to ensure a contiguous network
        dist_to_core = abs(chunk[0] - core_chunk[0]) + abs(chunk[1] - core_chunk[1])
        score += dist_to_core * 0.1

        if score < best_score:
            best_score = score
            best_chunk = chunk

    # If all valid chunks are heavily penalized (score > 1000),
    # the bot will still pick the "least bad" one, ensuring it doesn't just freeze.
    bot.explore_target_chunk = best_chunk


def _maybe_share_explore_claim(bot, ct: Controller):
    target_chunk = bot.explore_target_chunk
    if target_chunk is None:
        return

    claim_marker = marker.create_explore_claim_marker(
        target_chunk,
        utils.direction_toward(ct.get_position(), bot.explore_target_pos)
        if bot.explore_target_pos is not None
        else None,
        ct.get_current_round(),
        (ct.get_map_width() + perception.CHUNK_SIZE - 1) // perception.CHUNK_SIZE,
        (ct.get_map_height() + perception.CHUNK_SIZE - 1) // perception.CHUNK_SIZE,
    )
    if utils.place_marker_around(ct, ct.get_position(), claim_marker):
        bot.logger.log(f"Shared explore claim marker for chunk {target_chunk}")


def execute(bot, ct: Controller):
    map_width = ct.get_map_width()
    map_height = ct.get_map_height()
    current_pos = ct.get_position()
    current_chunk = (
        current_pos[0] // perception.CHUNK_SIZE,
        current_pos[1] // perception.CHUNK_SIZE,
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
            bot.logger.log("Map fully explored or unreachable!")
            # bot.builder_mode = BuilderMode.FINDING_ORE
            return

    # 3. Execute Movement and Catch A* Failures
    if bot.explore_target_pos is not None:
        _maybe_share_explore_claim(bot, ct)
        bot.logger.log(
            f"Exploring towards chunk {bot.explore_target_chunk} at {bot.explore_target_pos}"
        )

        path_found = navigation.move_towards(bot, ct, bot.explore_target_pos)

        if path_found:
            bot.explore_stuck_turns = 0
            return

        bot.explore_stuck_turns += 1
        bot.logger.log(
            f"Exploration stalled for target {bot.explore_target_chunk} "
            f"({bot.explore_stuck_turns}/{EXPLORE_STUCK_RETRY_TURNS})."
        )

        if bot.explore_stuck_turns < EXPLORE_STUCK_RETRY_TURNS:
            return

        bot.logger.log(
            f"Target {bot.explore_target_chunk} deemed unreachable after retries. Blacklisting."
        )
        bot.unreachable_chunks.add(bot.explore_target_chunk)
        bot.explore_target_chunk = None
        bot.explore_target_pos = None
        bot.explore_stuck_turns = 0
