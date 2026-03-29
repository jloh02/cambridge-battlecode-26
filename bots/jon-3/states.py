from enum import Enum, auto


class BuilderMode(Enum):
    FINDING_ORE = auto()
    EXPLORING = auto()
    TILING_BACK = auto()
