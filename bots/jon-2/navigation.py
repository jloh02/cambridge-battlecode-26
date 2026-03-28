from cambc import Controller, Direction, Position
import utils


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


def get_bugnav_dir(
    bot,
    ct: Controller,
    from_pos: Position,
    target_pos: Position,
    directions: list[Direction],
) -> Direction | None:
    state = bot.bugnav_state
    best_dir = min(
        directions, key=lambda d: from_pos.add(d).distance_squared(target_pos)
    )
    current_dist = from_pos.distance_squared(target_pos)

    if utils.is_passable(ct, from_pos, best_dir) and (
        not state["bugging"] or current_dist < state["start_dist"]
    ):
        return best_dir

    if not state["bugging"]:
        for step in range(1, 4):
            ccw_dir = best_dir
            for _ in range(step):
                ccw_dir = ccw_dir.rotate_left()
            if ccw_dir in directions and utils.is_passable(ct, from_pos, ccw_dir):
                return ccw_dir

            cw_dir = best_dir
            for _ in range(step):
                cw_dir = cw_dir.rotate_right()
            if cw_dir in directions and utils.is_passable(ct, from_pos, cw_dir):
                return cw_dir
        return None
    else:
        heading = state.get("heading", best_dir)
        side = state.get("side", 1)
        for direction in get_sweep_dirs(heading, side, directions):
            if utils.is_passable(ct, from_pos, direction):
                return direction
    return None


def try_bugnav_move(
    bot, ct: Controller, target_pos: Position, directions: list[Direction]
) -> bool:
    state = bot.bugnav_state
    current_pos = ct.get_position()
    best_dir = min(
        directions, key=lambda d: current_pos.add(d).distance_squared(target_pos)
    )
    current_dist = current_pos.distance_squared(target_pos)
    move_dir = None

    if utils.is_passable(ct, current_pos, best_dir) and (
        not state["bugging"] or current_dist < state["start_dist"]
    ):
        move_dir = best_dir
        state["bugging"] = False
        state["heading"] = move_dir
        state["visited"] = set()
    else:
        if not state["bugging"]:
            state["bugging"] = True
            state["start_dist"] = current_dist
            state["visited"] = {current_pos}
            for step in range(1, 4):
                ccw_dir = best_dir
                for _ in range(step):
                    ccw_dir = ccw_dir.rotate_left()
                if ccw_dir in directions and utils.is_passable(
                    ct, current_pos, ccw_dir
                ):
                    move_dir = ccw_dir
                    state["side"] = 1
                    break

                cw_dir = best_dir
                for _ in range(step):
                    cw_dir = cw_dir.rotate_right()
                if cw_dir in directions and utils.is_passable(ct, current_pos, cw_dir):
                    move_dir = cw_dir
                    state["side"] = -1
                    break
        else:
            if current_pos in state.get("visited", set()):
                bot.logger.log("Bugnav full loop detected! Target is unreachable.")
                state["bugging"] = False
                return False

            state["visited"].add(current_pos)
            for direction in get_sweep_dirs(
                state.get("heading", best_dir), state.get("side", 1), directions
            ):
                if utils.is_passable(ct, current_pos, direction):
                    move_dir = direction
                    break

    if move_dir is None:
        return False
    next_pos = current_pos.add(move_dir)

    if bot.builder_mode != "tiling_back" and ct.can_build_road(next_pos):
        ct.build_road(next_pos)
    elif (
        bot.builder_mode == "tiling_back"
        and utils.is_passable(ct, current_pos, move_dir)
        and not ct.can_move(move_dir)
    ):
        return False

    if ct.can_move(move_dir):
        ct.move(move_dir)
        state["heading"] = move_dir
        return True
    return False


def move_towards(
    bot, ct: Controller, target_pos: Position, directions: list[Direction]
):
    if ct.get_position() == target_pos:
        return
    ct.draw_indicator_dot(target_pos, 0, 255, 0)
    try_bugnav_move(bot, ct, target_pos, directions)
