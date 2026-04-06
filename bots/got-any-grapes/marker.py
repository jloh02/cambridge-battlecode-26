from cambc import Direction, Enum, Position


class MarkerType(Enum):
    CONNECTED_CONVEYOR = 0
    EXPLORE_CLAIM = 1
    ORE_LOCATION = 2
    CONNECTED_HARVESTER = 3
    ASSAULT_CLAIM = 4
    ASSAULT_SPAWN = 5


class SymmetryType(Enum):
    UNKNOWN = 0
    HORIZONTAL = 1
    VERTICAL = 2
    ROTATIONAL = 3


TOTAL_BITS = 32
TYPE_BITS = 3
ROUND_BITS = 10
ROUND_MOD = 1 << ROUND_BITS
DIRECTION_ORDER = [d for d in Direction if d != Direction.CENTRE]
DIRECTION_BITS = max(1, (len(DIRECTION_ORDER) - 1).bit_length())
_DIRECTION_TO_INDEX = {direction: idx for idx, direction in enumerate(DIRECTION_ORDER)}
ASSAULT_OWNER_BITS = 5
ASSAULT_OWNER_MASK = (1 << ASSAULT_OWNER_BITS) - 1
WORLD_ORIENTATION_MAGIC = 0xD
WORLD_ORIENTATION_SHIFT = 28
WORLD_SYMMETRY_SHIFT = 24
WORLD_CONFIDENCE_SHIFT = 20
WORLD_REJECTED_SHIFT = 17
WORLD_SALIENT_SHIFT = 12
WORLD_MASK = (1 << 4) - 1


class _DecodedWorldOrientation:
    __slots__ = ("symmetry", "confidence", "rejected_mask", "salient_flags")

    def __init__(self, symmetry, confidence: int, rejected_mask: int, salient_flags: int):
        self.symmetry = symmetry
        self.confidence = confidence
        self.rejected_mask = rejected_mask
        self.salient_flags = salient_flags


def is_recent_round(marker_round: int, current_round: int, ttl_rounds: int) -> bool:
    round_delta = (current_round - marker_round) % ROUND_MOD
    return round_delta <= ttl_rounds


def decode_marker(
    marker_value: int,
    *,
    map_width: int | None = None,
    map_height: int | None = None,
    chunk_cols: int | None = None,
    chunk_rows: int | None = None,
):
    orientation = parse_world_orientation_marker(marker_value)
    if orientation is not None:
        symmetry, confidence, rejected_mask, salient_flags = orientation
        return _DecodedWorldOrientation(symmetry, confidence, rejected_mask, salient_flags)

    if (
        map_width is not None
        and map_height is not None
        and parse_ore_marker(marker_value, map_width, map_height) is not None
    ):
        pos, round_mod = parse_ore_marker(marker_value, map_width, map_height)
        return type(
            "_DecodedMarker",
            (),
            {
                "kind": MarkerType.ORE_LOCATION,
                "position": pos,
                "round_mod": round_mod,
                "chunk": None,
                "direction": None,
            },
        )()

    if (
        map_width is not None
        and map_height is not None
        and parse_connected_conveyor_marker(marker_value, map_width, map_height) is not None
    ):
        pos, round_mod = parse_connected_conveyor_marker(marker_value, map_width, map_height)
        return type(
            "_DecodedMarker",
            (),
            {
                "kind": MarkerType.CONNECTED_CONVEYOR,
                "position": pos,
                "round_mod": round_mod,
                "chunk": None,
                "direction": None,
            },
        )()

    if (
        chunk_cols is not None
        and chunk_rows is not None
        and parse_explore_claim_marker(marker_value, chunk_cols, chunk_rows) is not None
    ):
        chunk, direction, round_mod = parse_explore_claim_marker(
            marker_value, chunk_cols, chunk_rows
        )
        return type(
            "_DecodedMarker",
            (),
            {
                "kind": MarkerType.EXPLORE_CLAIM,
                "position": None,
                "round_mod": round_mod,
                "chunk": chunk,
                "direction": direction,
            },
        )()

    return None


def is_recent_record(record, current_round: int, ttl_rounds: int) -> bool:
    return is_recent_round(getattr(record, "round_mod", 0), current_round, ttl_rounds)


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


def assault_claim_owner_tag(entity_id: int) -> int:
    return entity_id & ASSAULT_OWNER_MASK


def create_assault_claim_marker(
    anchor_pos: Position,
    owner_tag: int,
    current_round: int,
    map_width: int,
    map_height: int,
) -> int:
    x_bits = max(1, (map_width - 1).bit_length())
    y_bits = max(1, (map_height - 1).bit_length())
    payload = (anchor_pos.x << y_bits) | anchor_pos.y
    payload = (payload << ASSAULT_OWNER_BITS) | (owner_tag & ASSAULT_OWNER_MASK)
    payload = (payload << ROUND_BITS) | (current_round % ROUND_MOD)
    return (payload << TYPE_BITS) | MarkerType.ASSAULT_CLAIM.value


def create_assault_spawn_marker(
    spawn_pos: Position,
    current_round: int,
    map_width: int,
    map_height: int,
) -> int:
    return _create_position_marker(
        MarkerType.ASSAULT_SPAWN,
        spawn_pos,
        current_round,
        map_width,
        map_height,
    )


def create_world_orientation_marker(
    *,
    symmetry: SymmetryType,
    confidence: int,
    rejected_mask: int,
    current_round: int,
    salient_flags: int = 0,
) -> int:
    return (
        (WORLD_ORIENTATION_MAGIC << WORLD_ORIENTATION_SHIFT)
        | ((int(symmetry.value) & WORLD_MASK) << WORLD_SYMMETRY_SHIFT)
        | ((confidence & WORLD_MASK) << WORLD_CONFIDENCE_SHIFT)
        | ((rejected_mask & 0x7) << WORLD_REJECTED_SHIFT)
        | ((salient_flags & 0x1F) << WORLD_SALIENT_SHIFT)
        | (current_round % ROUND_MOD)
    )


def parse_world_orientation_marker(marker_value: int) -> tuple[SymmetryType, int, int, int] | None:
    if (marker_value >> WORLD_ORIENTATION_SHIFT) != WORLD_ORIENTATION_MAGIC:
        return None
    try:
        symmetry = SymmetryType((marker_value >> WORLD_SYMMETRY_SHIFT) & WORLD_MASK)
    except ValueError:
        symmetry = SymmetryType.UNKNOWN
    confidence = (marker_value >> WORLD_CONFIDENCE_SHIFT) & WORLD_MASK
    rejected_mask = (marker_value >> WORLD_REJECTED_SHIFT) & 0x7
    salient_flags = (marker_value >> WORLD_SALIENT_SHIFT) & 0x1F
    return symmetry, confidence, rejected_mask, salient_flags


def parse_assault_claim_marker(
    marker_value: int,
    map_width: int,
    map_height: int,
) -> tuple[Position, int, int] | None:
    marker_type = MarkerType(marker_value & ((1 << TYPE_BITS) - 1))
    if marker_type != MarkerType.ASSAULT_CLAIM:
        return None

    x_bits = max(1, (map_width - 1).bit_length())
    y_bits = max(1, (map_height - 1).bit_length())
    payload = marker_value >> TYPE_BITS
    round_mask = (1 << ROUND_BITS) - 1
    marker_round = payload & round_mask
    payload >>= ROUND_BITS
    owner_tag = payload & ASSAULT_OWNER_MASK
    payload >>= ASSAULT_OWNER_BITS
    y_mask = (1 << y_bits) - 1
    y = payload & y_mask
    x = payload >> y_bits

    if x >= map_width or y >= map_height:
        return None

    return Position(x, y), owner_tag, marker_round


def parse_assault_spawn_marker(
    marker_value: int,
    map_width: int,
    map_height: int,
) -> tuple[Position, int] | None:
    return _parse_position_marker(
        MarkerType.ASSAULT_SPAWN,
        marker_value,
        map_width,
        map_height,
    )


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
