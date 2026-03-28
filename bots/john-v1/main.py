from cambc import Controller, Direction, EntityType, Environment, Position
from builder import Builder
from core import Core


class Player:
    def __init__(self):
        self.entity = None  # Placeholder for the dynamically initialized entity

    def run(self, ct: Controller):
        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            if not isinstance(self.entity, Core):
                self.entity = Core(ct)
            self.entity.run(ct)
        elif etype == EntityType.BUILDER_BOT:
            if not isinstance(self.entity, Builder):
                self.entity = Builder(ct)
            self.entity.run(ct)
