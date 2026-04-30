from typing import Any, TYPE_CHECKING
import logging

from .agent import Agent
from .action import create_valid_actions
from common import axl
from common.protocol import MESSAGE_TYPE_STATE_UPDATE, PROTOCOL_VERSION

if TYPE_CHECKING:
    from .sim import Simulation


logger = logging.getLogger(__name__)


def send_states_to_agents(sim: "Simulation"):
    for agent in sim.agents:
        message = create_state_message(sim, agent)
        send_to_agent(agent, message)


def send_to_agent(agent: Agent, message: dict[str, Any]):
    axl.send(message, agent.public_key)
    content = message["content"]
    logger.info(
        "sent state sim_id=%s tick=%s agent=%s public_key=%s valid_actions=%s visible_tiles=%s",
        content["sim_id"],
        content["tick"],
        agent.id,
        agent.public_key,
        len(content["valid_actions"]),
        len(content["visible_map"]),
    )


def create_state_message(sim: "Simulation", agent: Agent) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "message_type": MESSAGE_TYPE_STATE_UPDATE,
        "content": create_state_content(sim, agent),
    }


def create_state_content(sim: "Simulation", agent: Agent) -> dict[str, Any]:
    agent.clamp_metrics()
    game_over = bool(getattr(sim, "game_over", False))
    return {
        "sim_id": sim.id,
        "tick": sim.iteration,
        "temp": sim.temp,
        "sim_status": {
            "game_over": game_over,
            "end_reason": getattr(sim, "end_reason", None),
            "ended_tick": getattr(sim, "ended_tick", None),
            "alive_count": sum(1 for sim_agent in sim.agents if sim_agent.alive),
            "max_ticks": getattr(sim, "max_ticks", None),
        },
        "agent": {
            "id": agent.id,
            "public_key": agent.public_key,
            "position": {
                "x": agent.pos_x,
                "y": agent.pos_y,
            },
            "alive": agent.alive,
            "health": agent.health,
            "mental_health": agent.mental_health,
            "hunger": agent.hunger,
            "thirst": agent.thirst,
            "warmth": agent.warmth,
            "strength": agent.strength,
            "stance": agent.stance,
            "status": list(agent.status),
            "action_budget": agent.action_budget,
            "inventory": serialize_inventory(agent.inventory),
            "death_tick": agent.death_tick,
            "death_cause": agent.death_cause,
            "killed_by": agent.killed_by,
        },
        "visible_map": create_visible_map(sim, agent),
        "valid_actions": [] if game_over or not agent.alive else create_valid_actions(sim, agent),
        "scoreboard": sim.scoreboard(),
        "results": sim.results() if game_over or not agent.alive else None,
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
                "occupants": [
                    {
                        "id": occupant.id,
                        "public_key": occupant.public_key,
                        "position": {
                            "x": occupant.pos_x,
                            "y": occupant.pos_y,
                        },
                        "alive": occupant.alive,
                    }
                    for occupant in tile.occupants
                ],
                "resources": serialize_inventory(tile.resources),
                "shelters": list(tile.shelters.keys()),
                "storages": list(tile.storages.keys()),
                "crops": [crop.copy() for crop in tile.crops],
            }
        )

    return visible_map


def serialize_inventory(inventory: dict[Any, int]) -> dict[str, int]:
    return {
        str(resource_type): amount
        for resource_type, amount in inventory.items()
        if amount > 0
    }
