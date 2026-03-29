from cambc import Controller, EntityType
from core_bot import CoreBot
from builder_bot import BuilderBot
import random

random.seed(1)


class Player:
    def __init__(self):
        # We start with no specific bot initialized.
        self.robot = None

    def run(self, ct: Controller) -> None:
        # On the first turn, check what we are and initialize the correct class.
        if self.robot is None:
            etype = ct.get_entity_type()
            if etype == EntityType.CORE:
                self.robot = CoreBot()
            elif etype == EntityType.BUILDER_BOT:
                self.robot = BuilderBot()

        # Delegate the run execution to the specific bot instance
        if self.robot is not None:
            self.robot.run(ct)
