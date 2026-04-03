from __future__ import annotations

from dataclasses import dataclass

import assault
from cambc import Controller, EntityType, Environment, Position


ORE_ENVIRONMENTS = {
    Environment.ORE_TITANIUM,
    Environment.ORE_AXIONITE,
}


@dataclass(frozen=True, slots=True)
class VisibleTarget:
    entity_id: int
    position: Position
    entity_type: EntityType
    hp: int


class SentinelBot:
    def _visible_targets(
        self,
        ct: Controller,
    ) -> tuple[list[VisibleTarget], set[Position]]:
        targets: list[VisibleTarget] = []
        friendly_builder_positions: set[Position] = set()
        my_team = ct.get_team()
        for entity_id in ct.get_nearby_entities():
            entity_type = ct.get_entity_type(entity_id)
            if entity_type == EntityType.MARKER:
                continue
            position = ct.get_position(entity_id)
            if ct.get_team(entity_id) == my_team:
                if entity_type == EntityType.BUILDER_BOT:
                    friendly_builder_positions.add(position)
                continue
            targets.append(
                VisibleTarget(
                    entity_id=entity_id,
                    position=position,
                    entity_type=entity_type,
                    hp=ct.get_hp(entity_id),
                )
            )
        return targets, friendly_builder_positions

    def _adjacent_anchor_harvester(
        self,
        ct: Controller,
        targets: list[VisibleTarget],
    ) -> Position | None:
        current_pos = ct.get_position()
        candidates = [
            target.position
            for target in targets
            if target.entity_type == EntityType.HARVESTER
            and assault.manhattan(current_pos, target.position) == 1
            and ct.get_tile_env(target.position) in ORE_ENVIRONMENTS
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda position: (position.x, position.y))

    def _target_priority(
        self,
        target: VisibleTarget,
        *,
        connected_cluster: set[Position],
        prefer_core_over_logistics: bool,
    ) -> int:
        if target.entity_type in assault.TURRET_TYPES:
            return 0
        if target.entity_type == EntityType.CORE:
            return 1 if prefer_core_over_logistics else 2
        if (
            target.position in connected_cluster
            and target.entity_type in assault.CONNECTED_LOGISTICS_TYPES
        ):
            return 2 if prefer_core_over_logistics else 1
        return 3

    def run(self, ct: Controller) -> None:
        targets, friendly_builder_positions = self._visible_targets(ct)
        if not targets:
            return

        anchor_harvester = self._adjacent_anchor_harvester(ct, targets)
        visible_enemies = [
            assault.VisibleEnemy(
                position=target.position,
                entity_type=target.entity_type,
            )
            for target in targets
        ]
        connected_cluster = (
            assault.connected_enemy_logistics_cluster(anchor_harvester, visible_enemies)
            if anchor_harvester is not None
            else set()
        )
        enemy_logistics_count = sum(
            1
            for target in targets
            if target.position in connected_cluster
            and target.position != anchor_harvester
            and target.entity_type in assault.CONNECTED_LOGISTICS_TYPES
        )
        prefer_core_over_logistics = (
            anchor_harvester is not None and enemy_logistics_count <= 1
        )
        current_pos = ct.get_position()

        legal_targets = [
            target
            for target in targets
            if not (
                anchor_harvester is not None
                and target.entity_type == EntityType.HARVESTER
                and target.position == anchor_harvester
            )
            and target.position not in friendly_builder_positions
            and ct.can_fire(target.position)
        ]
        if not legal_targets:
            return

        chosen_target = min(
            legal_targets,
            key=lambda target: (
                self._target_priority(
                    target,
                    connected_cluster=connected_cluster,
                    prefer_core_over_logistics=prefer_core_over_logistics,
                ),
                target.hp,
                assault.distance_sq(current_pos, target.position),
                target.position.x,
                target.position.y,
            ),
        )
        ct.fire(chosen_target.position)
