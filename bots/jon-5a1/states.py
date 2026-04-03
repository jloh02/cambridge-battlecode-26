from enum import Enum, auto


class BuilderMode(Enum):
    FINDING_ORE = auto()
    EXPLORING = auto()
    TILING_BACK = auto()
    ASSAULTING = auto()


class TargetKind(Enum):
    CORE = auto()
    CONVEYOR = auto()


class ActionType(Enum):
    CONVEYOR = auto()
    BRIDGE = auto()
