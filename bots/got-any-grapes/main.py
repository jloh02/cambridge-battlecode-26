import utils
import time
import random
from core_bot import CoreBot
from builder_bot import BuilderBot
from sentinel_bot import SentinelBot
import timing
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
            elif etype in {EntityType.SENTINEL, EntityType.GUNNER}:
                self.robot = SentinelBot()

        # Delegate the run execution to the specific bot instance
        if self.robot is not None:
            self.robot.run(ct)

        if DEBUG_TIME:
            end_time = time.time_ns()
            elapsed_time = end_time - start_time
            if elapsed_time > timing.HARD_DECISION_BUDGET_NS:
                ct.draw_indicator_dot(ct.get_position(), 255, 0, 0)

            round_num = ct.get_current_round()
            if elapsed_time > timing.HARD_DECISION_BUDGET_NS or round_num % 25 == 0:
                if hasattr(self.robot, "turn_timing"):
                    tt = self.robot.turn_timing
                    print(
                        f"Turn {round_num}: total={elapsed_time / 1_000_000:.2f} ms "
                        f"perception={tt.get('perception_ns', 0) / 1_000_000:.2f} ms "
                        f"mode={tt.get('mode_ns', 0) / 1_000_000:.2f} ms"
                    )
                else:
                    print(f"Turn {round_num}: total={elapsed_time / 1_000_000:.2f} ms")
