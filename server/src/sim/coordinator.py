from typing import Any, TYPE_CHECKING
import logging

from .agent import Agent
from .action import create_valid_actions
from common import axl
from common.identity import agent_display_name
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
    agent.recalculate_inventory()
    agent.clamp_metrics()
    game_over = bool(getattr(sim, "game_over", False))
    return {
        "sim_id": sim.id,
        "tick": sim.iteration,
        "phase": getattr(sim, "phase", "day"),
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
            "name": _agent_name(agent),
            "ens_name": agent.profile.get("ens_name"),
            "public_key": agent.public_key,
            "profile": dict(agent.profile),
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
            "status_since": dict(agent.status_since),
            "action_budget": agent.action_budget,
            "inventory_weight": agent.inventory_weight,
            "carry_capacity": agent.carry_capacity,
            "reputation": agent.reputation,
            "inventory": serialize_inventory(agent.inventory),
            "death_tick": agent.death_tick,
            "death_cause": agent.death_cause,
            "killed_by": agent.killed_by,
        },
        "visible_map": create_visible_map(sim, agent),
        "valid_actions": [] if game_over or not agent.alive else create_valid_actions(sim, agent),
        "scoreboard": sim.scoreboard(),
        "recent_events": list(getattr(sim, "event_log", [])[-8:]),
        "active_events": list(getattr(sim, "active_events", [])[-5:]),
        "recent_trades": list(getattr(sim, "trade_log", [])[-8:]),
        "limits": {
            "action_budget_capacity": agent.action_budget,
            "max_context_tokens": 16000,
            "carry_capacity": agent.carry_capacity,
        },
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
                    _visible_agent(agent, occupant)
                    for occupant in tile.occupants
                ],
                "resources": serialize_inventory(tile.resources),
                "shelters": list(tile.shelters.keys()),
                "storages": list(tile.storages.keys()),
                "crops": [crop.copy() for crop in tile.crops],
                "traps": _visible_traps(tile, agent),
                "hazard": tile.hazard,
            }
        )

    return visible_map


def _visible_agent(agent: Agent, occupant: Agent) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": occupant.id,
        "name": _agent_name(occupant),
        "ens_name": occupant.profile.get("ens_name"),
        "public_key": occupant.public_key,
        "profile": dict(occupant.profile),
        "position": {
            "x": occupant.pos_x,
            "y": occupant.pos_y,
        },
        "alive": occupant.alive,
        "condition": _condition_tags(occupant),
        "reputation": occupant.reputation,
        "tradeable_inventory": serialize_inventory(occupant.inventory),
    }
    if occupant is not agent:
        payload["relation"] = {
            "trust": agent.trust.get(occupant.id, 50.0),
            "grudge": agent.grudges.get(occupant.id, 0.0),
        }
    return payload


def _agent_name(agent: Agent) -> str:
    return agent_display_name(agent_id=agent.id, public_key=agent.public_key, profile=agent.profile)


def _condition_tags(agent: Agent) -> list[str]:
    tags = []
    if agent.health < 45:
        tags.append("wounded")
    if agent.hunger > 65:
        tags.append("hungry")
    if agent.thirst > 65:
        tags.append("thirsty")
    if agent.warmth < 45:
        tags.append("cold")
    if agent.mental_health < 45:
        tags.append("stressed")
    if "sick" in agent.status:
        tags.append("sick")
    return tags or ["stable"]


def _visible_traps(tile: Any, agent: Agent) -> list[dict[str, Any]]:
    traps = []
    for trap in getattr(tile, "traps", []):
        own_trap = trap.get("owner") == agent.public_key
        traps.append(
            {
                "owner": "self" if own_trap else "unknown",
                "ready_iteration": trap.get("ready_iteration") if own_trap else None,
            }
        )
    return traps


def serialize_inventory(inventory: dict[Any, int]) -> dict[str, int]:
    return {
        str(resource_type): amount
        for resource_type, amount in inventory.items()
        if amount > 0
    }
