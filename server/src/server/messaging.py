import asyncio
import json

from common import axl
import sim
from sim.action import Action
from .state import State
from .config import MAP_SIZE, PROTOCOL_VERSION


async def handle_message(sender, msg, state: State):
    msg = json.loads(msg)
    if msg.get("protocol_version") != PROTOCOL_VERSION:
        print(f"Received message with unsupported protocol version: {msg.get('protocol_version')}")
        return

    message_type = msg.get("message_type")
    if message_type == 'MATCHMAKING_JOIN':
        state.add_to_queue(sender)
        if state.queue_ready():
            print("Matchmaking queue is ready, creating new game instance")
            agents, seed = state.pick_new_sim_agents()
            state.sim_instances.append(sim.setup(agents, seed))
    elif message_type == "AGENT_ACTION":
        handle_agent_action(sender, msg, state)


def handle_agent_action(sender: str, msg: dict, state: State):
    sim_and_agent = state.find_sim_and_agent(sender)
    if sim_and_agent is None:
        print(f"Received AGENT_ACTION from unknown agent: {sender}")
        return

    sim_instance, agent = sim_and_agent
    content = msg.get("content", msg)

    try:
        tick = _extract_action_tick(content, msg, sim_instance.iteration)
        action = Action.from_dict(_extract_action_payload(content, msg))
    except (TypeError, ValueError) as exc:
        print(f"Invalid AGENT_ACTION from {sender}: {exc}")
        return

    agent.queue_action(tick, action)


def _extract_action_tick(content: object, msg: dict, default_tick: int) -> int:
    if isinstance(content, dict):
        if "tick" in content:
            return int(content["tick"])
        if "iteration" in content:
            return int(content["iteration"])

    if "tick" in msg:
        return int(msg["tick"])
    if "iteration" in msg:
        return int(msg["iteration"])
    return default_tick


def _extract_action_payload(content: object, msg: dict) -> object:
    if isinstance(content, dict):
        nested_action = content.get("action")
        if isinstance(nested_action, dict):
            return nested_action
        if isinstance(nested_action, str):
            return {
                key: value
                for key, value in content.items()
                if key not in ("tick", "iteration")
            }
        if "action_type" in content or "type" in content:
            return {
                key: value
                for key, value in content.items()
                if key not in ("tick", "iteration")
            }

    nested_action = msg.get("action")
    if nested_action is not None:
        return nested_action

    return msg


async def recv_loop(state: State):
    while True:
        received = axl.recv()
        if received is None:
            await asyncio.sleep(0.1)
            continue

        sender, msg = received
        await handle_message(sender, msg, state)
