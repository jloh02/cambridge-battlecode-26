from cambc import Enum, GameConstants, Position, Controller, EntityType, Environment


class MarkerState:
    def __init__(self):
        self.titanium_locations: set[Position] = set()
        self.axionite_locations: set[Position] = set()
