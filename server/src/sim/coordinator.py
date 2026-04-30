from typing import Any, TYPE_CHECKING

from .agent import Agent
from common import axl

if TYPE_CHECKING:
    from .sim import Simulation


PROTOCOL_VERSION = "1.0"
MESSAGE_TYPE = "state_update"


def send_states_to_agents(sim: "Simulation"):
    for agent in sim.agents:
        message = create_state_message(sim, agent)
        send_to_agent(agent, message)


def send_to_agent(agent: Agent, message: dict[str, Any]):
    axl.send(message, agent.public_key)


def create_state_message(sim: "Simulation", agent: Agent) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "message_type": MESSAGE_TYPE,
        "content": create_state_content(sim, agent),
    }


def create_state_content(sim: "Simulation", agent: Agent) -> dict[str, Any]:
    return {
        "tick": sim.iteration,
        "temp": sim.temp,
        "agent": {
            "id": agent.id,
            "health": agent.health,
            "mental_health": agent.mental_health,
            "hunger": agent.hunger,
            "thirst": agent.thirst,
            "warmth": agent.warmth,
            "inventory": serialize_inventory(agent.inventory),
        },
        "visible_map": create_visible_map(sim, agent),
    }


def create_visible_map(sim: "Simulation", agent: Agent) -> list[dict[str, Any]]:
    visible_map = []

    for (x, y) in agent.visible_tiles:
        tile = sim.map.grid[y][x]
        visible_map.append(
            {
                "x": tile.pos_x,
                "y": tile.pos_y,
                "type": tile.type.value,
                "occupants": [occupant.id for occupant in tile.occupants],
                "resources": serialize_inventory(tile.resources),
            }
        )

    return visible_map


def serialize_inventory(inventory: dict[Any, int]) -> dict[str, int]:
    return {
        str(resource_type): amount
        for resource_type, amount in inventory.items()
        if amount > 0
    }
