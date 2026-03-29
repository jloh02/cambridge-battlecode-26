import random
from cambc import Controller, Direction

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]

random.seed(1)

def init(self):
    self.num_spawned = 0

def run(self, ct: Controller):
    BUFFER = 500
    # 1. Check our bank account
    titanium, axionite = ct.get_global_resources()
    
    # 2. Calculate the price of the next Builder
    # 0 spawned = 50. 1 spawned = 60. 2 spawned = 70. etc.
    next_builder_cost = 50 + (self.num_spawned * 10)
    
    # Optional: Set a maximum limit so you don't accidentally spend 
    # ALL your titanium on 100 bots and trap your Core!
    MAX_BOTS = 15 
    
    # 3. If we have enough money (and haven't hit the cap), spawn one!
    if titanium >= next_builder_cost + BUFFER and self.num_spawned < MAX_BOTS:
        
        # Find an empty tile around the Core
        valid_spawns = [d for d in DIRECTIONS if ct.can_spawn(ct.get_position().add(d))]
        
        if valid_spawns:
            spawn_pos = ct.get_position().add(random.choice(valid_spawns))
            
            # Buy the bot
            ct.spawn_builder(spawn_pos)
            self.num_spawned += 1
            
            print(f"Core spawned Builder #{self.num_spawned} for {next_builder_cost} Titanium!")
            print(f"Remaining Titanium: {titanium - next_builder_cost}")