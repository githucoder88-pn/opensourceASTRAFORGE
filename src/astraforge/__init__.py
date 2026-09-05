"""AstraForge — open-source infrastructure for reliable AI work.

GOAL -> PLAN -> EXECUTION -> VERIFICATION -> EVIDENCE -> ARTIFACT
"""

from astraforge.core.config import Config
from astraforge.core.factory import build_engine, make_goal
from astraforge.execution.engine import Engine, RunResult
from astraforge.models.core import Goal, Plan, Run, Task

__version__ = "0.1.0"

__all__ = [
    "Config",
    "Engine",
    "Goal",
    "Plan",
    "Run",
    "RunResult",
    "Task",
    "__version__",
    "build_engine",
    "make_goal",
]
