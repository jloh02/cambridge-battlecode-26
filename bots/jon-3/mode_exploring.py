from cambc import Controller, Position
import utils
import navigation
import perception
from states import BuilderMode


def _ensure_chunks_initialized(bot, map_width: int, map_height: int):
    """Initializes the grid of map chunks if not already done."""
    if bot.all_map_chunks is None:
        chunk_cols = (map_width + perception.CHUNK_SIZE - 1) // perception.CHUNK_SIZE
        chunk_rows = (map_height + perception.CHUNK_SIZE - 1) // perception.CHUNK_SIZE
        bot.all_map_chunks = [
            (cx, cy) for cx in range(chunk_cols) for cy in range(chunk_rows)
        ]


def _get_chunk_center(
    chunk: tuple[int, int], map_width: int, map_height: int
) -> Position:
    """Returns the center coordinate of a given chunk."""
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
        return True


def _select_nearest_unexplored_chunk(bot, current_chunk: tuple[int, int]):
    """Finds the best unexplored chunk and sets it as the target."""
    unexplored_chunks = [c for c in bot.all_map_chunks if c not in bot.explored_tiles]
    if not unexplored_chunks:
        return

    core_chunk = (
        bot.core_pos.x // perception.CHUNK_SIZE,
        bot.core_pos.y // perception.CHUNK_SIZE,
    )
    unexplored_chunks.sort(
        key=lambda c: (
            abs(c[0] - current_chunk[0]) + abs(c[1] - current_chunk[1]),
            abs(c[0] - core_chunk[0]) + abs(c[1] - core_chunk[1]),
            c[1],
            c[0],
        )
    )
    bot.explore_target_chunk = unexplored_chunks[0]


def execute(bot, ct: Controller):
    map_width = ct.get_map_width()
    map_height = ct.get_map_height()
    current_pos = ct.get_position()
    current_chunk = (
        current_pos.x // perception.CHUNK_SIZE,
        current_pos.y // perception.CHUNK_SIZE,
    )

    _ensure_chunks_initialized(bot, map_width, map_height)

    target_cleared = _clear_reached_target(bot)
    if target_cleared:
        bot.builder_mode = BuilderMode.FINDING_ORE
        return

    if bot.explore_target_chunk is None:
        _select_nearest_unexplored_chunk(bot, current_chunk)
        if bot.explore_target_chunk is not None:
            bot.explore_target_pos = _get_chunk_center(
                bot.explore_target_chunk, map_width, map_height
            )

    # Fallback to ensure target pos is synced
    if bot.explore_target_pos is None and bot.explore_target_chunk is not None:
        bot.explore_target_pos = _get_chunk_center(
            bot.explore_target_chunk, map_width, map_height
        )

    if bot.explore_target_pos is not None:
        bot.logger.log(f"exploring towards {bot.explore_target_pos}")
        navigation.move_towards(bot, ct, bot.explore_target_pos, utils.DIRECTIONS)
