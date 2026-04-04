from cambc import Direction, Enum, Position


class MarkerType(Enum):
    CONNECTED_CONVEYOR = 0
    EXPLORE_CLAIM = 1
    ORE_LOCATION = 2
    CONNECTED_HARVESTER = 3


TOTAL_BITS = 32
TYPE_BITS = 3
ROUND_BITS = 10
ROUND_MOD = 1 << ROUND_BITS
DIRECTION_ORDER = [d for d in Direction if d != Direction.CENTRE]
DIRECTION_BITS = max(1, (len(DIRECTION_ORDER) - 1).bit_length())
_DIRECTION_TO_INDEX = {direction: idx for idx, direction in enumerate(DIRECTION_ORDER)}


def is_recent_round(marker_round: int, current_round: int, ttl_rounds: int) -> bool:
    round_delta = (current_round - marker_round) % ROUND_MOD
    return round_delta <= ttl_rounds


def create_ore_marker(
    ore_pos: Position,
    current_round: int,
    map_width: int,
    map_height: int,
) -> int:
    return _create_position_marker(
        MarkerType.ORE_LOCATION, ore_pos, current_round, map_width, map_height
    )


def parse_ore_marker(
    marker_value: int,
    map_width: int,
    map_height: int,
) -> tuple[Position, int] | None:
    return _parse_position_marker(
        MarkerType.ORE_LOCATION, marker_value, map_width, map_height
    )


def create_connected_conveyor_marker(
    conveyor_pos: Position,
    current_round: int,
    map_width: int,
    map_height: int,
) -> int:
    return _create_position_marker(
        MarkerType.CONNECTED_CONVEYOR,
        conveyor_pos,
        current_round,
        map_width,
        map_height,
    )


def parse_connected_conveyor_marker(
    marker_value: int,
    map_width: int,
    map_height: int,
) -> tuple[Position, int] | None:
    return _parse_position_marker(
        MarkerType.CONNECTED_CONVEYOR,
        marker_value,
        map_width,
        map_height,
    )


def create_connected_harvester_marker(
    harvester_pos: Position,
    current_round: int,
    map_width: int,
    map_height: int,
) -> int:
    return _create_position_marker(
        MarkerType.CONNECTED_HARVESTER,
        harvester_pos,
        current_round,
        map_width,
        map_height,
    )


def parse_connected_harvester_marker(
    marker_value: int,
    map_width: int,
    map_height: int,
) -> tuple[Position, int] | None:
    return _parse_position_marker(
        MarkerType.CONNECTED_HARVESTER,
        marker_value,
        map_width,
        map_height,
    )


def create_explore_claim_marker(
    chunk: tuple[int, int],
    direction: Direction | None,
    current_round: int,
    chunk_cols: int,
    chunk_rows: int,
) -> int:
    x_bits = max(1, (chunk_cols - 1).bit_length())
    y_bits = max(1, (chunk_rows - 1).bit_length())
    direction_idx = _DIRECTION_TO_INDEX.get(direction, 0)
    chunk_payload = (chunk[0] << y_bits) | chunk[1]
    payload = chunk_payload
    payload = (payload << DIRECTION_BITS) | direction_idx
    payload = (payload << ROUND_BITS) | (current_round % ROUND_MOD)
    return (payload << TYPE_BITS) | MarkerType.EXPLORE_CLAIM.value


def parse_explore_claim_marker(
    marker_value: int,
    chunk_cols: int,
    chunk_rows: int,
) -> tuple[tuple[int, int], Direction, int] | None:
    marker_type = MarkerType(marker_value & ((1 << TYPE_BITS) - 1))
    if marker_type != MarkerType.EXPLORE_CLAIM:
        return None

    x_bits = max(1, (chunk_cols - 1).bit_length())
    y_bits = max(1, (chunk_rows - 1).bit_length())
    payload = marker_value >> TYPE_BITS
    round_mask = (1 << ROUND_BITS) - 1
    marker_round = payload & round_mask
    payload >>= ROUND_BITS
    direction_mask = (1 << DIRECTION_BITS) - 1
    direction_idx = payload & direction_mask
    payload >>= DIRECTION_BITS
    y_mask = (1 << y_bits) - 1
    chunk_y = payload & y_mask
    chunk_x = payload >> y_bits

    if (
        chunk_x >= chunk_cols
        or chunk_y >= chunk_rows
        or direction_idx >= len(DIRECTION_ORDER)
    ):
        return None

    return (chunk_x, chunk_y), DIRECTION_ORDER[direction_idx], marker_round


def _create_position_marker(
    marker_type: MarkerType,
    pos: Position,
    current_round: int,
    map_width: int,
    map_height: int,
) -> int:
    x_bits = max(1, (map_width - 1).bit_length())
    y_bits = max(1, (map_height - 1).bit_length())
    payload = (pos.x << y_bits) | pos.y
    payload = (payload << ROUND_BITS) | (current_round % ROUND_MOD)
    return (payload << TYPE_BITS) | marker_type.value


def _parse_position_marker(
    expected_type: MarkerType,
    marker_value: int,
    map_width: int,
    map_height: int,
) -> tuple[Position, int] | None:
    marker_type = MarkerType(marker_value & ((1 << TYPE_BITS) - 1))
    if marker_type != expected_type:
        return None

    x_bits = max(1, (map_width - 1).bit_length())
    y_bits = max(1, (map_height - 1).bit_length())
    payload = marker_value >> TYPE_BITS
    round_mask = (1 << ROUND_BITS) - 1
    marker_round = payload & round_mask
    payload >>= ROUND_BITS
    y_mask = (1 << y_bits) - 1
    y = payload & y_mask
    x = payload >> y_bits

    if x >= map_width or y >= map_height:
        return None

    return Position(x, y), marker_round
