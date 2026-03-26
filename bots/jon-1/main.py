from cambc import Controller, Direction, EntityType, Environment, Position
import core
import builder

# non-centre directions
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]


class Player:
    def __init__(self):
        core.init(self)
        builder.init(self)

    def run(self, ct: Controller) -> None:
        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            core.run(self, ct)
        elif etype == EntityType.BUILDER_BOT:
            builder.run(self, ct)
