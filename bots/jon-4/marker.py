from cambc import Enum, Position


class MarkerType(Enum):
    EXPLORE_CLAIM = 0


TOTAL_BITS = 32
TYPE_BITS = 3
CLAIM_ROUND_BITS = 12
CLAIM_ROUND_MOD = 1 << CLAIM_ROUND_BITS


def parse_explore_claim_marker(
    marker_value: int,
    chunk_cols: int,
    chunk_rows: int,
) -> tuple[tuple[int, int], int] | None:
    marker_type = MarkerType(marker_value & ((1 << TYPE_BITS) - 1))

    if marker_type != MarkerType.EXPLORE_CLAIM:
        return None

    x_bits = max(1, (chunk_cols - 1).bit_length())
    y_bits = max(1, (chunk_rows - 1).bit_length())
    payload = marker_value >> TYPE_BITS
    round_mask = (1 << CLAIM_ROUND_BITS) - 1
    claim_round = payload & round_mask
    chunk_payload = payload >> CLAIM_ROUND_BITS
    y_mask = (1 << y_bits) - 1
    chunk_y = chunk_payload & y_mask
    chunk_x = chunk_payload >> y_bits

    if chunk_x >= chunk_cols or chunk_y >= chunk_rows:
        return None

    return (chunk_x, chunk_y), claim_round


def create_explore_claim_marker(
    chunk: tuple[int, int],
    current_round: int,
    chunk_cols: int,
    chunk_rows: int,
) -> int:
    x_bits = max(1, (chunk_cols - 1).bit_length())
    y_bits = max(1, (chunk_rows - 1).bit_length())
    chunk_payload = (chunk[0] << y_bits) | chunk[1]
    payload = (chunk_payload << CLAIM_ROUND_BITS) | (current_round % CLAIM_ROUND_MOD)
    return (payload << TYPE_BITS) | MarkerType.EXPLORE_CLAIM.value


def is_recent_claim_round(
    claim_round: int, current_round: int, ttl_rounds: int
) -> bool:
    round_delta = (current_round - claim_round) % CLAIM_ROUND_MOD
    return round_delta <= ttl_rounds
