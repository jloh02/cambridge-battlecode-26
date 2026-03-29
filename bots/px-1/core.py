import random
from cambc import Controller, Direction

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]

random.seed(1)

def init(self):
    self.num_spawned = 0

def run(self, ct: Controller):
    # Just pump out 3 bots and let them do the thinking
    if self.num_spawned < 3:
        valid_spawns = [d for d in DIRECTIONS if ct.can_spawn(ct.get_position().add(d))]
        if valid_spawns:
            spawn_pos = ct.get_position().add(random.choice(valid_spawns))
            ct.spawn_builder(spawn_pos)
            self.num_spawned += 1