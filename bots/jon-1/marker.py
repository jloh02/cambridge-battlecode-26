from cambc import Enum, GameConstants, Position, Controller, EntityType, Environment


class MarkerType(Enum):
    ORE_LOCATION = 0
    ORE_CHOPE = 1


TOTAL_BITS = 32
TYPE_BITS = 3

"""
32-bit integer marker encoding the current round number, used for communication between bots
Format: [marker value (up to 29 bits)][type (3 bits, LSB)]

Type 0: determine absolute ore locations in priority order
    Format:
      - repeated[x_bits y_bits between 4-6 bits each, depending on the map size, total 29 bits max]
      - NOT zero-padded
    TODO: convert to relative locations

Type 1: chope marker
    Format: [round number (11 bits)][]
"""


class MarkerState:
    def __init__(self):
        self.ore_locations = set()

    def scan_markers(self, ct: Controller):
        for id in ct.get_nearby_entities():
            if (
                ct.get_entity_type(id) == EntityType.MARKER
                and ct.get_team(id) == ct.get_team()
            ):
                marker_value = ct.get_marker_value(id)
                self.parse_marker_value(
                    marker_value, ct.get_map_width(), ct.get_map_height()
                )

    def parse_marker_value(self, marker_value: int, max_width: int, max_height: int):
        marker_type = MarkerType(marker_value & ((1 << TYPE_BITS) - 1))
        x_bits = max_width.bit_length()
        y_bits = max_height.bit_length()
        if marker_type == MarkerType.ORE_LOCATION:
            self.update_ore_locations(
                _ore_marker_to_positions(marker_value, x_bits, y_bits)
            )

    def update_ore_locations(self, ore_directions):
        for ore_direction in ore_directions:
            self.ore_locations.add(ore_direction)

    def create_ore_marker(self, max_width, max_height):
        return _create_ore_marker(self.ore_locations, max_width, max_height)


def _get_marker_type_str(type: MarkerType) -> str:
    return bin(type.value)[2:].zfill(TYPE_BITS)


def _get_ore_coordinates(position: Position, x_bits: int, y_bits: int):
    return bin(position.x)[2:].zfill(x_bits) + bin(position.y)[2:].zfill(y_bits)


def _ore_marker_to_positions(
    marker_value: int, x_bits: int, y_bits: int
) -> list[Position]:
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


def _create_ore_marker(
    ore_directions: list[Position], max_width: int, max_height: int
) -> int:
    x_bits = max_width.bit_length()
    y_bits = max_height.bit_length()
    value = ""
    for pos in ore_directions:
        value += _get_ore_coordinates(pos, x_bits, y_bits)
        if len(value) + x_bits + y_bits > TOTAL_BITS - TYPE_BITS:
            break

    return int(
        value + _get_marker_type_str(MarkerType.ORE_LOCATION),
        2,
    )
