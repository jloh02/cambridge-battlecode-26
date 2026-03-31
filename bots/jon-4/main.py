import utils
import time
import random
from core_bot import CoreBot
from builder_bot import BuilderBot
from cambc import Controller, EntityType

random.seed(1)

DEBUG_TIME = utils.DEBUG


class Player:
    def __init__(self):
        # We start with no specific bot initialized.
        self.robot = None

    def run(self, ct: Controller) -> None:
        if DEBUG_TIME:
            start_time = time.time_ns()

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

        if DEBUG_TIME:
            end_time = time.time_ns()
            elapsed_time = end_time - start_time
            if elapsed_time > 1_800_000:  # 1.9 ms in nanoseconds
                ct.draw_indicator_dot(
                    ct.get_position(), 255, 0, 0
                )  # Red dot if we are close to the time limit
            print(f"Turn execution time: {elapsed_time / 1_000_000:.2f} ms")
