from .agent import Agent
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sim import Simulation

def valid_action(sim: "Simulation", agent: Agent, action: str) -> bool:
    return True

def execute_action(sim: "Simulation", agent: Agent, action: str):
    pass