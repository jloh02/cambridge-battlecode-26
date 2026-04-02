"""Translate TurnPlan objects into real controller calls."""

from __future__ import annotations

from dataclasses import dataclass

from cambc import Controller, EntityType, GameError

from .decision import (
    BuildDecision,
    BuildKind,
    ConvertDecision,
    DestroyDecision,
    FireDecision,
    HealDecision,
    IndicatorDotDecision,
    IndicatorLineDecision,
    LaunchDecision,
    RotateDecision,
    TurnPlan,
)
from .sense import TurnContext


@dataclass(slots=True)
class ExecutionResult:
    marker_executed: bool = False
    action_executed: bool = False
    move_executed: bool = False


def _execute_build(controller: Controller, decision: BuildDecision) -> bool:
    def try_direct_build() -> bool:
        if decision.kind == BuildKind.BUILDER_BOT:
            if controller.can_spawn(decision.position):
                controller.spawn_builder(decision.position)
                return True
            return False
        if decision.kind == BuildKind.CONVEYOR:
            if decision.direction is not None and controller.can_build_conveyor(decision.position, decision.direction):
                controller.build_conveyor(decision.position, decision.direction)
                return True
            return False
        if decision.kind == BuildKind.SPLITTER:
            if decision.direction is not None and controller.can_build_splitter(decision.position, decision.direction):
                controller.build_splitter(decision.position, decision.direction)
                return True
            return False
        if decision.kind == BuildKind.ARMOURED_CONVEYOR:
            if decision.direction is not None and controller.can_build_armoured_conveyor(decision.position, decision.direction):
                controller.build_armoured_conveyor(decision.position, decision.direction)
                return True
            return False
        if decision.kind == BuildKind.BRIDGE:
            if decision.target is not None and controller.can_build_bridge(decision.position, decision.target):
                controller.build_bridge(decision.position, decision.target)
                return True
            return False
        if decision.kind == BuildKind.HARVESTER:
            if controller.can_build_harvester(decision.position):
                controller.build_harvester(decision.position)
                return True
            return False
        if decision.kind == BuildKind.ROAD:
            if controller.can_build_road(decision.position):
                controller.build_road(decision.position)
                return True
            return False
        if decision.kind == BuildKind.BARRIER:
            if controller.can_build_barrier(decision.position):
                controller.build_barrier(decision.position)
                return True
            return False
        if decision.kind == BuildKind.FOUNDRY:
            if controller.can_build_foundry(decision.position):
                controller.build_foundry(decision.position)
                return True
            return False
        if decision.kind == BuildKind.GUNNER:
            if decision.direction is not None and controller.can_build_gunner(decision.position, decision.direction):
                controller.build_gunner(decision.position, decision.direction)
                return True
            return False
        if decision.kind == BuildKind.SENTINEL:
            if decision.direction is not None and controller.can_build_sentinel(decision.position, decision.direction):
                controller.build_sentinel(decision.position, decision.direction)
                return True
            return False
        if decision.kind == BuildKind.BREACH:
            if decision.direction is not None and controller.can_build_breach(decision.position, decision.direction):
                controller.build_breach(decision.position, decision.direction)
                return True
            return False
        if decision.kind == BuildKind.LAUNCHER:
            if controller.can_build_launcher(decision.position):
                controller.build_launcher(decision.position)
                return True
            return False
        return False

    if try_direct_build():
        return True
    if decision.replace_existing and controller.can_destroy(decision.position):
        controller.destroy(decision.position)
        return try_direct_build()
    return False


def _execute_action(controller: Controller, plan: TurnPlan) -> bool:
    action = plan.action
    if action is None:
        return False
    if isinstance(action, BuildDecision):
        return _execute_build(controller, action)
    if isinstance(action, FireDecision):
        if controller.can_fire(action.target):
            controller.fire(action.target)
            return True
        return False
    if isinstance(action, RotateDecision):
        if not hasattr(controller, "rotate"):
            return False
        try:
            controller.rotate(action.direction)
            return True
        except GameError:
            return False
    if isinstance(action, HealDecision):
        if controller.can_heal(action.position):
            controller.heal(action.position)
            return True
        return False
    if isinstance(action, DestroyDecision):
        if controller.can_destroy(action.position):
            controller.destroy(action.position)
            return True
        return False
    if isinstance(action, LaunchDecision):
        if controller.can_launch(action.bot_position, action.target):
            controller.launch(action.bot_position, action.target)
            return True
        return False
    if isinstance(action, ConvertDecision):
        if action.amount <= 0 or not hasattr(controller, "convert"):
            return False
        try:
            controller.convert(action.amount)
            return True
        except GameError:
            return False
    return False


def _draw_indicator_line(controller: Controller, decision: IndicatorLineDecision) -> None:
    controller.draw_indicator_line(
        decision.pos_a,
        decision.pos_b,
        decision.r,
        decision.g,
        decision.b,
    )


def _draw_indicator_dot(controller: Controller, decision: IndicatorDotDecision) -> None:
    controller.draw_indicator_dot(decision.pos, decision.r, decision.g, decision.b)


def execute_plan(controller: Controller, context: TurnContext, plan: TurnPlan) -> ExecutionResult:
    """Apply a TurnPlan conservatively.

    The executor never raises on illegal actions. It always checks legality
    first because the whole point of this layer is to keep strategy code simple
    and make failures visible in one place.
    """

    result = ExecutionResult()

    for indicator_line in plan.indicator_lines:
        _draw_indicator_line(controller, indicator_line)
    for indicator_dot in plan.indicator_dots:
        _draw_indicator_dot(controller, indicator_dot)

    if plan.marker is not None and controller.can_place_marker(plan.marker.position):
        controller.place_marker(plan.marker.position, plan.marker.value)
        result.marker_executed = True

    result.action_executed = _execute_action(controller, plan)

    if plan.move is not None and context.entity_type == EntityType.BUILDER_BOT:
        if controller.can_move(plan.move.direction):
            controller.move(plan.move.direction)
            result.move_executed = True

    return result
