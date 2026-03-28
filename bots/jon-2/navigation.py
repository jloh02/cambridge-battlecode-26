from cambc import Controller, Direction, Position
import utils
from states import BuilderMode


def get_sweep_dirs(
    heading: Direction, side: int, valid_directions: list[Direction]
) -> list[Direction]:
    curr = heading
    for _ in range(3):
        curr = curr.rotate_right() if side == 1 else curr.rotate_left()

    sweep = []
    for _ in range(7):
        if curr in valid_directions:
            sweep.append(curr)
        curr = curr.rotate_left() if side == 1 else curr.rotate_right()
    return sweep


def compute_bugnav_step(
    bot,
    ct: Controller,
    current_pos: Position,
    target_pos: Position,
    directions: list[Direction],
    current_state: dict,
) -> tuple[Direction | None, dict]:

    state = current_state.copy()

    # 1. Initialize the M-Line Start Anchor
    # This must be set ONCE when the bot first starts moving towards a new target.
    if "original_start" not in state:
        state["original_start"] = current_pos

    best_dir = min(
        directions, key=lambda d: current_pos.add(d).distance_squared(target_pos)
    )
    current_dist = current_pos.distance_squared(target_pos)
    move_dir = None

    # 2. Check if we are standing on the M-Line
    is_on_m_line = False
    if state.get("bugging"):
        dist_to_line = utils.distance_to_line(
            current_pos, state["original_start"], target_pos
        )
        # Tolerance of 0.6 units thickens the line to catch grid-crossings
        is_on_m_line = dist_to_line <= 0.6

    # 3. The Bug2 Release Condition
    if utils.is_passable(ct, current_pos, best_dir) and (
        not state.get("bugging")
        or (is_on_m_line and current_dist < state.get("hit_dist", float("inf")))
    ):
        move_dir = best_dir
        state["bugging"] = False
        state["heading"] = move_dir
    else:
        # 4. Entering or Continuing Bugging
        if not state.get("bugging"):
            state["bugging"] = True
            # Record the exact distance when we hit the wall
            state["hit_dist"] = current_dist

            for step in range(1, 4):
                ccw_dir = best_dir
                for _ in range(step):
                    ccw_dir = ccw_dir.rotate_left()
                if ccw_dir in directions and utils.is_passable(
                    ct, current_pos, ccw_dir
                ):
                    move_dir = ccw_dir
                    state["heading"] = move_dir
                    state["side"] = 1
                    break

                cw_dir = best_dir
                for _ in range(step):
                    cw_dir = cw_dir.rotate_right()
                if cw_dir in directions and utils.is_passable(ct, current_pos, cw_dir):
                    move_dir = cw_dir
                    state["heading"] = move_dir
                    state["side"] = -1
                    break
        else:
            # Wall following
            for direction in get_sweep_dirs(
                state.get("heading", best_dir), state.get("side", 1), directions
            ):
                if utils.is_passable(ct, current_pos, direction):
                    move_dir = direction
                    state["heading"] = move_dir
                    break

    return move_dir, state


def try_bugnav_move(
    bot, ct: Controller, target_pos: Position, directions: list[Direction]
) -> bool:
    current_pos = ct.get_position()

    # Ask the logic function what we should do
    move_dir, new_state = compute_bugnav_step(
        bot, ct, current_pos, target_pos, directions, bot.bugnav_state
    )

    if move_dir is None:
        return False

    next_pos = current_pos.add(move_dir)

    # 1. Handle Building Logic
    if bot.builder_mode != BuilderMode.TILING_BACK and ct.can_build_road(next_pos):
        ct.build_road(next_pos)

    if bot.builder_mode == BuilderMode.TILING_BACK and not utils.is_passable(
        ct, current_pos, move_dir
    ):
        return False

    # 2. Execute Move and Update REAL state
    if ct.can_move(move_dir):
        ct.move(move_dir)

        # ONLY override the bot's state if the move physically succeeded
        bot.bugnav_state = new_state
        return True

    return False


def move_towards(
    bot, ct: Controller, target_pos: Position, directions: list[Direction]
):
    if ct.get_position() == target_pos:
        return
    ct.draw_indicator_dot(target_pos, 0, 255, 0)
    try_bugnav_move(bot, ct, target_pos, directions)
