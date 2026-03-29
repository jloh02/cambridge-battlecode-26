from cambc import Controller, EntityType
import core
import builder


class Player:
    def __init__(self):
        # We only set up the routing state here.
        self.initialized = False
        self.entity_type = None

    def run(self, ct: Controller) -> None:
        # 1. Lazy Initialization: Only runs on this unit's very first turn
        if not self.initialized:
            self.entity_type = ct.get_entity_type()

            if self.entity_type == EntityType.CORE:
                core.init(self)
            elif self.entity_type == EntityType.BUILDER_BOT:
                builder.init(self)

            self.initialized = True

        # 2. Execution Routing with Crash Protection
        try:
            if self.entity_type == EntityType.CORE:
                core.run(self, ct)
            elif self.entity_type == EntityType.BUILDER_BOT:
                builder.run(self, ct)
        except Exception as e:
            # Prevents a single bot's crash from taking down the whole team
            print(f"[{self.entity_type} {ct.get_id()}] error: {e}")
