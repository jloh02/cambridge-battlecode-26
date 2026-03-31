from cambc import Enum, Position, Controller, EntityType


class MarkerType(Enum):
    ORE_LOCATION = 0
    ORE_CHOPE = 1


TOTAL_BITS = 32
TYPE_BITS = 3


def _get_marker_type_str(type: MarkerType) -> str:
    return bin(type.value)[2:].zfill(TYPE_BITS)


def _get_ore_coordinates(position: Position, x_bits: int, y_bits: int) -> str:
    return bin(position.x)[2:].zfill(x_bits) + bin(position.y)[2:].zfill(y_bits)


def parse_ore_marker(
    marker_value: int, max_width: int, max_height: int
) -> list[Position]:
    """Decodes a marker value into a list of ore positions."""
    marker_type = MarkerType(marker_value & ((1 << TYPE_BITS) - 1))

    if marker_type != MarkerType.ORE_LOCATION:
        return []

    x_bits = max_width.bit_length()
    y_bits = max_height.bit_length()

    # Marker layout is [payload][type], where type is the 3 LSB.
    value_str = bin(marker_value >> TYPE_BITS)[2:]
    positions = []
    chunk_bits = x_bits + y_bits

    # No zero padding: drop any incomplete prefix so decoding starts on a full chunk.
    remainder = len(value_str) % chunk_bits
    if remainder:
        value_str = value_str[remainder:]

    for i in range(0, len(value_str), chunk_bits):
        if i + chunk_bits > len(value_str):
            break

        x = int(value_str[i : i + x_bits], 2)
        y = int(value_str[i + x_bits : i + x_bits + y_bits], 2)
        positions.append(Position(x, y))

    return positions


def create_ore_marker(
    ore_positions: list[Position], max_width: int, max_height: int
) -> int:
    """Encodes a list of ore positions into a 32-bit marker integer."""
    x_bits = max_width.bit_length()
    y_bits = max_height.bit_length()
    value = ""

    for pos in ore_positions:
        value += _get_ore_coordinates(pos, x_bits, y_bits)
        if len(value) + x_bits + y_bits > TOTAL_BITS - TYPE_BITS:
            break

    return int(
        value + _get_marker_type_str(MarkerType.ORE_LOCATION),
        2,
    )
