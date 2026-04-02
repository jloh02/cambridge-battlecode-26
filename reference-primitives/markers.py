"""Marker encoding and decoding helpers.

Markers are the only documented shared communication channel between allied
units. The engine stores just a single u32 value, so we keep a tiny versioned
schema here instead of scattering magic numbers throughout the strategies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from cambc import Direction, Environment


class MarkerKind(IntEnum):
    """Logical marker message kinds used by the MVP bots."""

    CLAIM_TITANIUM = 1
    CLAIM_AXIONITE = 2
    ROUTE_TO_CORE = 3
    DEFENSE_ALERT = 4
    FRONTIER_CLAIM = 5
    BLOCKED_FRONT = 6
    SECTOR_TITANIUM_HINT = 7
    SECTOR_BLOCKED_HINT = 8


class ClaimLaneStatus(IntEnum):
    """Lane status packed into the titanium claim payload."""

    CLAIMED = 0
    ROUTING = 1
    DONE = 2
    REPAIR = 3


SCHEMA_VERSION = 1
SCHEMA_SHIFT = 28
KIND_SHIFT = 24
PAYLOAD_SHIFT = 8
PAYLOAD_MASK = 0xFFFF
ROUND_MASK = 0xFF
CLAIM_STATUS_SHIFT = 14
CLAIM_STATUS_MASK = 0x3
CLAIM_OWNER_MASK = (1 << CLAIM_STATUS_SHIFT) - 1

CARDINAL_DIRECTION_TO_CODE = {
    Direction.NORTH: 1,
    Direction.EAST: 2,
    Direction.SOUTH: 3,
    Direction.WEST: 4,
}
CODE_TO_CARDINAL_DIRECTION = {
    value: key for key, value in CARDINAL_DIRECTION_TO_CODE.items()
}


@dataclass(frozen=True, slots=True)
class MarkerMessage:
    """Decoded marker payload.

    `age_round_mod` stores the low 8 bits of the round the marker was written.
    The bots only use markers as short-lived hints, so byte-sized freshness is
    enough and keeps the schema simple.
    """

    kind: MarkerKind
    payload: int
    age_round_mod: int


def _encode(kind: MarkerKind, payload: int, round_num: int) -> int:
    return (
        (SCHEMA_VERSION << SCHEMA_SHIFT)
        | (int(kind) << KIND_SHIFT)
        | ((payload & PAYLOAD_MASK) << PAYLOAD_SHIFT)
        | (round_num & ROUND_MASK)
    )


def decode_marker(value: int) -> MarkerMessage | None:
    """Decode a marker value if it matches this repository's schema."""

    if value >> SCHEMA_SHIFT != SCHEMA_VERSION:
        return None
    kind_value = (value >> KIND_SHIFT) & 0xF
    try:
        kind = MarkerKind(kind_value)
    except ValueError:
        return None
    payload = (value >> PAYLOAD_SHIFT) & PAYLOAD_MASK
    round_mod = value & ROUND_MASK
    return MarkerMessage(kind=kind, payload=payload, age_round_mod=round_mod)


def marker_age(current_round: int, message: MarkerMessage) -> int:
    """Compute age from round modulo arithmetic.

    The marker schema only stores the low byte of the round. This helper keeps
    freshness checks consistent and explicit.
    """

    return (current_round - message.age_round_mod) & ROUND_MASK


def is_recent_marker(current_round: int, message: MarkerMessage, horizon: int = 16) -> bool:
    return marker_age(current_round, message) <= horizon


def encode_claim(resource_env: Environment, bot_id: int, round_num: int) -> int:
    if resource_env == Environment.ORE_TITANIUM:
        kind = MarkerKind.CLAIM_TITANIUM
    elif resource_env == Environment.ORE_AXIONITE:
        kind = MarkerKind.CLAIM_AXIONITE
    else:
        raise ValueError(f"Claims only make sense on ore tiles, got {resource_env!r}")
    return _encode(kind, bot_id, round_num)


def pack_claim_status(owner_id: int, status: ClaimLaneStatus | int) -> int:
    return ((int(status) & CLAIM_STATUS_MASK) << CLAIM_STATUS_SHIFT) | (owner_id & CLAIM_OWNER_MASK)


def unpack_claim_status(payload: int) -> tuple[int, ClaimLaneStatus]:
    status = ClaimLaneStatus((payload >> CLAIM_STATUS_SHIFT) & CLAIM_STATUS_MASK)
    owner_id = payload & CLAIM_OWNER_MASK
    return owner_id, status


def encode_titanium_lane_status(owner_id: int, status: ClaimLaneStatus | int, round_num: int) -> int:
    return _encode(
        MarkerKind.CLAIM_TITANIUM,
        pack_claim_status(owner_id, status),
        round_num,
    )


def decode_titanium_lane_status(message: MarkerMessage) -> tuple[int, ClaimLaneStatus] | None:
    if message.kind != MarkerKind.CLAIM_TITANIUM:
        return None
    return unpack_claim_status(message.payload)


def encode_route(direction: Direction, round_num: int) -> int:
    try:
        payload = CARDINAL_DIRECTION_TO_CODE[direction]
    except KeyError as exc:
        raise ValueError(f"Route markers only support cardinal directions, got {direction!r}") from exc
    return _encode(MarkerKind.ROUTE_TO_CORE, payload, round_num)


def decode_route_direction(message: MarkerMessage) -> Direction | None:
    if message.kind != MarkerKind.ROUTE_TO_CORE:
        return None
    return CODE_TO_CARDINAL_DIRECTION.get(message.payload)


def encode_defense_alert(round_num: int, threat_score: int = 1) -> int:
    return _encode(MarkerKind.DEFENSE_ALERT, threat_score, round_num)


def encode_frontier_claim(bot_id: int, round_num: int) -> int:
    return _encode(MarkerKind.FRONTIER_CLAIM, bot_id, round_num)


def encode_blocked_front(round_num: int, severity: int = 1) -> int:
    return _encode(MarkerKind.BLOCKED_FRONT, severity, round_num)


def encode_sector_titanium_hint(sector_id: int, round_num: int) -> int:
    return _encode(MarkerKind.SECTOR_TITANIUM_HINT, sector_id, round_num)


def encode_sector_blocked_hint(sector_id: int, round_num: int) -> int:
    return _encode(MarkerKind.SECTOR_BLOCKED_HINT, sector_id, round_num)


def decode_sector_id(message: MarkerMessage) -> int | None:
    if message.kind not in (MarkerKind.SECTOR_TITANIUM_HINT, MarkerKind.SECTOR_BLOCKED_HINT):
        return None
    return message.payload
