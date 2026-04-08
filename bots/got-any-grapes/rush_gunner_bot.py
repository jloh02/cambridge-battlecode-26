from cambc import Controller, EntityType
import logger

class RushGunnerBot:
    '''
    You should only use this for Sentinels involved in the RUSH strategy.
    Otherwise, this is a terrible bot that just tries to shoot the core,
    or nothing at all.
    '''
    def __init__(self):
        self.enemy_core_pos = None

    def _refresh_enemy_core_memory(self, ct):
        my_team = ct.get_team()
        for unit_id in ct.get_nearby_units():
            if ct.get_entity_type(unit_id) != EntityType.CORE:
                continue
            if ct.get_team(unit_id) == my_team:
                continue
            self.enemy_core_pos = ct.get_position(unit_id)
            return

    def run(self, ct):
        self._refresh_enemy_core_memory(ct)

        if self.enemy_core_pos is None:
            return

        # Core shots must use the center tile.
        if ct.can_fire(self.enemy_core_pos):
            ct.fire(self.enemy_core_pos)
            return