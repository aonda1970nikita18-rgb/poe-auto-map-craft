from enum import Enum


class CellState(str, Enum):
    EMPTY = "empty"
    GRAY = "gray"
    HIGHLIGHTED = "highlighted"
    UNKNOWN = "unknown"


class ProgramState(str, Enum):
    IDLE = "idle"
    INITIALIZING = "initializing"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    ERROR = "error"