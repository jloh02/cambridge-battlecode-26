import time
import random
from cambc import Controller, Direction, EntityType, Environment, Position

random.seed(1)

STATE_EXPLORE = "explore"
STATE_SEEK = "seek"
STATE_TETHER = "tether"

# DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]


def _manhattan(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)

CONVEYOR_DIRS = [
    Direction.NORTH, 
    Direction.SOUTH, 
    Direction.EAST, 
    Direction.WEST
]

# Limit to up down left right for now since I can't handle slanted
DIRECTIONS = CONVEYOR_DIRS

def _best_dir_towards(ct: Controller, target_pos: Position, DIR) -> Direction:
    current = ct.get_position()
    best_dir = Direction.CENTRE
    best_dist = _manhattan(current, target_pos)
    valid_dirs = []

    for d in DIR:
        next_pos = current.add(d)
        if ct.get_tile_env(next_pos) != Environment.WALL and ct.get_tile_env(next_pos) != Environment.ORE_TITANIUM:
            valid_dirs.append(d)
            dist = _manhattan(next_pos, target_pos)
            if dist < best_dist:
                best_dist = dist
                best_dir = d

    # Slide along the wall if the direct path is blocked
    if best_dir == Direction.CENTRE and valid_dirs:
        best_dir = random.choice(valid_dirs)
    return best_dir

def _find_nearest_available_ore(ct: Controller, ore_type=Environment.ORE_TITANIUM) -> Position:
    current_pos = ct.get_position()
    nearest_ore = None
    best_dist = float('inf')

    # Pre-calculate occupied tiles to avoid slow nested loops
    # Using a set of (x,y) tuples makes lookups instant
    occupied_coords = set()
    for b_id in ct.get_nearby_buildings():
        pos = ct.get_position(b_id)
        occupied_coords.add((pos.x, pos.y))

    # Scan for the specified ore
    for pos in ct.get_nearby_tiles():
        if ct.get_tile_env(pos) == ore_type:
            
            # Make sure nobody has built here yet
            if (pos.x, pos.y) not in occupied_coords:
                
                # Check if it's the closest one we've seen so far
                dist = _manhattan(current_pos, pos)
                if dist < best_dist:
                    best_dist = dist
                    nearest_ore = pos
                    
    return nearest_ore

def _check_immediate_ore(ct: Controller, ore_type=Environment.ORE_TITANIUM):
    """Ultra-fast check of the 8 adjacent tiles for available ore."""
    current_pos = ct.get_position()
    
    # Quick lookup for occupied tiles
    occupied_coords = set()
    for b_id in ct.get_nearby_buildings():
        pos = ct.get_position(b_id)
        occupied_coords.add((pos.x, pos.y))

    # Check the 1-tile radius
    for d in DIRECTIONS:
        check_pos = current_pos.add(d)
        
        if ct.get_tile_env(check_pos) == ore_type:
            # Make sure nobody built on it
            if (check_pos.x, check_pos.y) not in occupied_coords:
                return check_pos # Found one! Return immediately.
                
    return None


def init(self):
    # Bots wake up and immediately start exploring
    self.state = STATE_EXPLORE
    self.target_pos = None
    self.core_pos = None
    self.explore_dir = random.choice(DIRECTIONS)

def run(self, ct: Controller):
    print(self.state)
    start_time = time.perf_counter()
    current_pos = ct.get_position()

    # Always figure out where the Core is so we can tether back to it
    if self.core_pos is None:
        
        # 1. Get your bot's own team so you have something to compare against
        # (Check your API docs: this might be ct.get_team(ct.get_id()) or just ct.get_team())
        my_team = ct.get_team(ct.get_id()) 

        # 2. Filter for Cores that ALSO match your team
        cores = [
            e_id for e_id in ct.get_nearby_entities() 
            if ct.get_entity_type(e_id) == EntityType.CORE 
            and ct.get_team(e_id) == my_team  # <--- The crucial ownership check!
        ]
        
        if cores:
            self.core_pos = ct.get_position(cores[0])
            print(f"Bot {ct.get_id()} locked onto friendly core at {self.core_pos.x}, {self.core_pos.y}")

    # STATE 1: EXPLORE
    if self.state == STATE_EXPLORE:
        # Scan for our own ore!
        found_ore = _find_nearest_available_ore(ct, Environment.ORE_TITANIUM)
        
        # If we saw ore, lock on and switch to SEEK
        if found_ore:
            self.target_pos = found_ore
            self.seek_visited = set()
            self.state = STATE_SEEK
            print(f"Bot {ct.get_id()} spotted ore at {found_ore.x}, {found_ore.y}!")
        
        # Otherwise, keep wandering
        else:
            # 1. Gather ONLY valid directions (can currently walk there OR can pave it)
            valid_dirs = []
            road_dirs = []
            
            for d in DIRECTIONS:
                next_pos = current_pos.add(d)
                can_pave = ct.can_build_road(next_pos)
                can_step = ct.can_move(d)
                
                # If we can do either action, it's a valid choice
                if can_pave or can_step:
                    valid_dirs.append(d)
                # Keep a separate list of unpaved tiles to prioritize
                if can_pave:
                    road_dirs.append(d)

            # If we aren't completely boxed in by indestructible walls/machines
            if valid_dirs:
                # --- THE MOMENTUM FIX ---
                # Only check if we NEED to change direction.
                # We change direction if our current path is blocked, OR if we want to turn down an unpaved road.
                current_dir_valid = self.explore_dir in valid_dirs
                needs_new_direction = not current_dir_valid or (road_dirs and self.explore_dir not in road_dirs)

                if needs_new_direction:
                    # Pick a new direction! 
                    candidates = road_dirs if road_dirs else valid_dirs
                    
                    if self.core_pos:
                        # Find the new outward path
                        best_dist = -1
                        best_candidates = []
                        for d in candidates:
                            next_pos = current_pos.add(d)
                            dist = _manhattan(next_pos, self.core_pos)
                            
                            if dist > best_dist:
                                best_dist = dist
                                best_candidates = [d]
                            elif dist == best_dist:
                                best_candidates.append(d)
                                
                        self.explore_dir = random.choice(best_candidates)
                    else:
                        self.explore_dir = random.choice(candidates)
                        
                # 4. Execute the move
                move_pos = current_pos.add(self.explore_dir)
                
                if ct.can_build_road(move_pos): 
                    ct.build_road(move_pos)
                    
                if ct.can_move(self.explore_dir): 
                    ct.move(self.explore_dir)
            else:
                # If this triggers, the bot is literally trapped in a 1x1 prison of machines/walls
                print(f"Bot {ct.get_id()} at {current_pos.x},{current_pos.y} has NO valid moves!")

    # STATE 2: SEEK
    if self.state == STATE_SEEK:
        # Check: Did another bot beat us here and build a harvester?
        someone_beat_us = False
        for b_id in ct.get_nearby_buildings():
            if ct.get_position(b_id) == self.target_pos:
                someone_beat_us = True
                break
                
        # If yes, abandon the mission and go back to exploring
        if someone_beat_us:
            self.state = STATE_EXPLORE
            self.target_pos = None
            return
        
        immediate_ore = _check_immediate_ore(ct)
        if immediate_ore and immediate_ore != self.target_pos:
            print(f"Bot {ct.get_id()} stumbled upon immediate ore! Hijacking mission.")
            self.target_pos = immediate_ore
            self.seek_visited = set()
            # We don't return here so it instantly builds the harvester on the next line!

        # If no, keep walking to the target
        if current_pos == self.target_pos or _manhattan(current_pos, self.target_pos) == 1:
            if ct.can_build_harvester(self.target_pos):
                ct.build_harvester(self.target_pos)
                self.state = STATE_TETHER
        else:
            # --- THE BREADCRUMB FIX ---
            
            # 1. Initialize memory if it doesn't exist
            if not hasattr(self, 'seek_visited'):
                self.seek_visited = set()
                
            # 2. Drop a breadcrumb on our current tile
            self.seek_visited.add((current_pos.x, current_pos.y))

            # 3. Gather all directions we can physically enter
            valid_dirs = []
            for d in DIRECTIONS:
                next_pos = current_pos.add(d)
                if ct.can_move(d) or ct.can_build_road(next_pos):
                    valid_dirs.append(d)

            if valid_dirs:
                # 4. Score each direction. 
                # Distance + a MASSIVE penalty (+1000) if we've already been there!
                def _score(d):
                    p = current_pos.add(d)
                    dist = _manhattan(p, self.target_pos)
                    penalty = 1000 if (p.x, p.y) in self.seek_visited else 0
                    return dist + penalty

                # min() will now flawlessly guide the bot around walls and out of dead ends
                best_dir = min(valid_dirs, key=_score)
                next_pos = current_pos.add(best_dir)
                
                # PRIORITY 1: Pave the road if we need to
                if not ct.can_move(best_dir):
                    if ct.can_build_road(next_pos): 
                        ct.build_road(next_pos)
                        
                # PRIORITY 2: Move safely
                if ct.can_move(best_dir): 
                    ct.move(best_dir)
            else:
                print(f"Bot {ct.get_id()} is completely trapped in SEEK state!")

    # STATE 3: TETHER
    if self.state == STATE_TETHER:
        # 1. Check if we've reached the core
        if current_pos == self.core_pos or _manhattan(current_pos, self.core_pos) <= 1:
            # We are at the core! Finish the last conveyor behind us before switching states
            if getattr(self, 'prev_pos', None) and self.prev_pos != self.target_pos:
                if ct.can_build_conveyor(self.prev_pos, self.prev_dir):
                    ct.build_conveyor(self.prev_pos, self.prev_dir)
                elif ct.can_destroy(self.prev_pos):
                    ct.destroy(self.prev_pos)
                    return # Action used, wait for next tick!
            
            # If the belt is fully connected, reset and explore
            self.state = STATE_EXPLORE  
            self.target_pos = None
            self.prev_pos = None
            self.prev_dir = None
            return

        # ---------------------------------------------------------
        # PRIORITY 1: Clean up and build the conveyor behind us
        # ---------------------------------------------------------
        if getattr(self, 'prev_pos', None) and self.prev_pos != self.target_pos:
            
            # Check if we already successfully built the conveyor here
            buildings_behind = [b for b in ct.get_nearby_buildings() if ct.get_position(b) == self.prev_pos]
            has_conveyor = any(ct.get_entity_type(b) == EntityType.CONVEYOR for b in buildings_behind)
            
            if not has_conveyor:
                # If we can build it, do it and end the turn
                if ct.can_build_conveyor(self.prev_pos, self.prev_dir):
                    ct.build_conveyor(self.prev_pos, self.prev_dir)
                    return # <-- END TICK
                    
                # If we can't build it, it's likely because the old road is still there. Destroy it!
                elif ct.can_destroy(self.prev_pos):
                    ct.destroy(self.prev_pos)
                    return # <-- END TICK

        # ---------------------------------------------------------
        # PRIORITY 2 & 3: Pave forward and Move
        # ---------------------------------------------------------
        move_dir = _best_dir_towards(ct, self.core_pos, CONVEYOR_DIRS)
        
        if move_dir != Direction.CENTRE:
            next_pos = current_pos.add(move_dir)
            
            # PRIORITY 2: If we can't move yet, we need to pave the road
            if not ct.can_move(move_dir):
                if ct.can_build_road(next_pos):
                    ct.build_road(next_pos)
                    return # <-- END TICK
                elif ct.can_destroy(next_pos): # Just in case a rock IS in the way
                    ct.destroy(next_pos)
                    return # <-- END TICK
                    
            # PRIORITY 3: The road is paved, we are ready to step forward!
            if ct.can_move(move_dir):
                self.prev_pos = current_pos
                self.prev_dir = move_dir
                ct.move(move_dir)
                return # <-- END TICK (Movement usually costs an action too!)
                
        else:
            print(f"Bot {ct.get_id()} is completely boxed in!")

                