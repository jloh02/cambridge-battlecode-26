"""Axionite pipeline planner.

Scaffolding for routing raw axionite through a refinery foundry into the
core. Because raw axionite delivered directly to the core is DESTROYED,
the only way axionite ore actually helps our TiEq is via a foundry:

    [harvester_on_ax_ore] -> conveyor -> [foundry] -> conveyor -> [core]
                                            ^
                                            | titanium input from
                                            | an adjacent connected
                                            | conveyor (existing lane)

The foundry needs at least THREE adjacent buildings:
  1. A conveyor carrying raw axionite from the ax harvester's output tile
  2. A conveyor carrying titanium from our existing connected Ti lane
  3. A conveyor carrying refined axionite OUT toward the core

This module exposes a single planner function
`plan_axionite_foundry_placement(bot, ct, ax_ore_pos)` that tries to find
a foundry tile satisfying those constraints, and returns a
`FoundryPlacement` describing the foundry tile plus the three conveyor
edges that the tiling-back pipeline must lay for the refinery to work.

When no valid placement exists (e.g. the ax ore is too far from any
connected Ti conveyor), the planner returns None and the caller should
skip the ax ore entirely. This keeps us from ever building a harvester
whose output will just flow into the core and be destroyed.

The planner is a pure helper; it does not call any build actions. The
caller is responsible for executing the pending builds in the usual
tiling-back pipeline order (foundry first on its tile, then the
supporting conveyors once the builder reaches each one).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from cambc import Controller, Direction, EntityType, Environment, Position

import utils


@dataclass(frozen=True)
class FoundryPlacement:
    """Concrete plan for a single axionite foundry.

    `foundry_pos` is where to call `ct.build_foundry`. `raw_ax_conveyor`
    is the tile the raw-ax conveyor must occupy (between ax harvester
    and foundry). `ti_input_conveyor` is the existing connected-Ti
    conveyor that will feed titanium into the foundry — the planner
    only accepts tiles where this conveyor already points INTO the
    foundry. `refined_output_conveyor` is the tile the outgoing refined
    axionite conveyor must occupy, heading toward the core.
    """

    ax_ore_pos: Position
    foundry_pos: Position
    raw_ax_conveyor_pos: Position
    raw_ax_conveyor_dir: Direction
    ti_input_conveyor_pos: Position
    refined_output_conveyor_pos: Position
    refined_output_conveyor_dir: Direction


ACTION_RADIUS_SQ = 2


def _is_empty_buildable(
    bot,
    ct: Controller,
    pos: Position,
    *,
    allow_builder: bool = False,
) -> bool:
    if pos is None:
        return False
    map_w = ct.get_map_width()
    map_h = ct.get_map_height()
    if not (0 <= pos.x < map_w and 0 <= pos.y < map_h):
        return False
    data = bot.grid.get((pos.x, pos.y))
    if data is None:
        return False
    env = data.get("env")
    if env != Environment.EMPTY:
        return False
    if data.get("building") is not None:
        return False
    if data.get("entity") is not None and not allow_builder:
        return False
    return True


def _cardinal_neighbors(pos: Position) -> Iterable[tuple[Direction, Position]]:
    yield Direction.NORTH, Position(pos.x, pos.y + 1)
    yield Direction.SOUTH, Position(pos.x, pos.y - 1)
    yield Direction.EAST, Position(pos.x + 1, pos.y)
    yield Direction.WEST, Position(pos.x - 1, pos.y)


def _find_adjacent_connected_ti_source(
    bot,
    ct: Controller,
    foundry_pos: Position,
    *,
    avoid: set[tuple[int, int]],
) -> Position | None:
    """Return the position of a neighbouring tile that is an already-
    connected friendly conveyor pointing INTO foundry_pos. Returns None
    if no such neighbour exists."""
    my_team = ct.get_team()
    connected = getattr(bot, "connected_friendly_conveyors", None) or {}
    for _, neighbor in _cardinal_neighbors(foundry_pos):
        neighbor_key = (neighbor.x, neighbor.y)
        if neighbor_key in avoid:
            continue
        if neighbor_key not in connected:
            continue
        data = bot.grid.get(neighbor_key)
        if data is None:
            continue
        if data.get("building_team") != my_team:
            continue
        build_dir = data.get("building_dir")
        if build_dir is None:
            continue
        # Is the build direction pointing at foundry_pos?
        dx, dy = build_dir.delta()
        if neighbor.x + dx == foundry_pos.x and neighbor.y + dy == foundry_pos.y:
            return neighbor
    return None


def _refined_output_candidate(
    bot,
    ct: Controller,
    foundry_pos: Position,
    *,
    avoid: set[tuple[int, int]],
    build_origin: Position | None = None,
) -> tuple[Position, Direction] | None:
    """Pick an empty buildable tile cardinal-adjacent to foundry_pos for
    the outgoing refined-ax conveyor. Prefers the neighbour that moves
    CLOSEST to the core."""
    core_pos = bot.core_pos
    if core_pos is None:
        return None
    best: tuple[int, Position, Direction] | None = None
    for direction, neighbor in _cardinal_neighbors(foundry_pos):
        neighbor_key = (neighbor.x, neighbor.y)
        if neighbor_key in avoid:
            continue
        if (
            build_origin is not None
            and build_origin.distance_squared(neighbor) > ACTION_RADIUS_SQ
        ):
            continue
        if not _is_empty_buildable(bot, ct, neighbor):
            continue
        # Direction the new conveyor should face: away from the
        # foundry, toward the core. We use the inverse of `direction`
        # (which goes foundry -> neighbor) so the conveyor at neighbor
        # faces back the other way IS WRONG — actually we want the
        # conveyor at `neighbor` to carry refined ax FURTHER from the
        # foundry, so its build_dir should be chosen to step toward
        # the core from `neighbor`.
        best_step_dx = core_pos.x - neighbor.x
        best_step_dy = core_pos.y - neighbor.y
        step_dir: Direction | None = None
        if abs(best_step_dx) >= abs(best_step_dy):
            step_dir = Direction.EAST if best_step_dx > 0 else Direction.WEST
        else:
            step_dir = Direction.NORTH if best_step_dy > 0 else Direction.SOUTH
        if step_dir is None:
            continue
        dist_to_core = abs(neighbor.x - core_pos.x) + abs(neighbor.y - core_pos.y)
        candidate = (dist_to_core, neighbor, step_dir)
        if best is None or candidate < best:
            best = candidate
    if best is None:
        return None
    return best[1], best[2]


def plan_axionite_foundry_placement(
    bot,
    ct: Controller,
    ax_ore_pos: Position,
    *,
    builder_pos: Position | None = None,
) -> FoundryPlacement | None:
    """Pure planner. Returns a foundry placement that would let an
    ax harvester on `ax_ore_pos` actually deliver refined axionite to
    the core, or None when no such placement exists. Does NOT mutate
    bot state or call any build actions."""
    if not utils.axionite_pipeline_ready(bot, ct):
        return None
    if bot.core_pos is None:
        return None

    my_team = ct.get_team()
    for raw_ax_dir, raw_ax_conveyor_pos in _cardinal_neighbors(ax_ore_pos):
        if builder_pos is not None and raw_ax_conveyor_pos != builder_pos:
            continue
        # The tile that carries raw ax out of the harvester must be a
        # buildable empty tile (we will lay a conveyor there later).
        if not _is_empty_buildable(
            bot,
            ct,
            raw_ax_conveyor_pos,
            allow_builder=builder_pos == raw_ax_conveyor_pos,
        ):
            continue
        # The conveyor at raw_ax_conveyor_pos points AWAY from the ax
        # harvester (into the foundry).
        for foundry_dir, foundry_pos in _cardinal_neighbors(raw_ax_conveyor_pos):
            # Skip the direction that would put the foundry back on
            # the ax ore.
            if (foundry_pos.x, foundry_pos.y) == (ax_ore_pos.x, ax_ore_pos.y):
                continue
            if not _is_empty_buildable(bot, ct, foundry_pos):
                continue
            # The raw_ax_conveyor must face INTO the foundry.
            dx, dy = foundry_dir.delta()
            raw_ax_conveyor_face = foundry_dir  # points from conveyor -> foundry
            _ = raw_ax_dir  # unused (direction from ore into conveyor)
            del dx, dy
            avoid: set[tuple[int, int]] = {
                (ax_ore_pos.x, ax_ore_pos.y),
                (raw_ax_conveyor_pos.x, raw_ax_conveyor_pos.y),
                (foundry_pos.x, foundry_pos.y),
            }
            ti_source = _find_adjacent_connected_ti_source(
                bot,
                ct,
                foundry_pos,
                avoid=avoid,
            )
            if ti_source is None:
                continue
            avoid.add((ti_source.x, ti_source.y))
            refined_plan = _refined_output_candidate(
                bot,
                ct,
                foundry_pos,
                avoid=avoid,
                build_origin=builder_pos,
            )
            if refined_plan is None:
                continue
            refined_pos, refined_dir = refined_plan
            return FoundryPlacement(
                ax_ore_pos=ax_ore_pos,
                foundry_pos=foundry_pos,
                raw_ax_conveyor_pos=raw_ax_conveyor_pos,
                raw_ax_conveyor_dir=raw_ax_conveyor_face,
                ti_input_conveyor_pos=ti_source,
                refined_output_conveyor_pos=refined_pos,
                refined_output_conveyor_dir=refined_dir,
            )
    # No valid placement.
    _ = my_team  # quiet the unused-variable linter if one is added later
    return None
