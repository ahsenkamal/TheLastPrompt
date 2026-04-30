import asyncio
import json
import logging

from common import axl
from common.protocol import (
    MESSAGE_TYPE_AGENT_ACTION,
    MESSAGE_TYPE_AGENT_MSG,
    MESSAGE_TYPE_MATCHMAKING_JOIN,
    PROTOCOL_VERSION,
)
import sim
from sim.action import Action
from .state import State


logger = logging.getLogger(__name__)


async def handle_message(sender, msg, state: State):
    try:
        msg = json.loads(msg)
    except json.JSONDecodeError as exc:
        logger.warning("received invalid JSON sender=%s error=%s", sender, exc)
        return
    if not isinstance(msg, dict):
        logger.warning("received non-object JSON sender=%s payload=%s", sender, msg)
        return

    if msg.get("protocol_version") != PROTOCOL_VERSION:
        logger.warning(
            "unsupported protocol sender=%s version=%s",
            sender,
            msg.get("protocol_version"),
        )
        return

    message_type = msg.get("message_type")
    logger.info("received message sender=%s type=%s", sender, message_type)
    if message_type == MESSAGE_TYPE_MATCHMAKING_JOIN:
        agent_public_key = _extract_sender_public_key(sender, msg)
        state.add_to_queue(agent_public_key)
        logger.info(
            "matchmaking join transport_sender=%s agent_public_key=%s queue_size=%s sim_size=%s",
            sender,
            agent_public_key,
            len(state.matchmaking_queue),
            state.sim_size,
        )
        if state.queue_ready():
            agents, seed = state.pick_new_sim_agents()
            logger.info("matchmaking ready agents=%s seed=%s", agents, seed)
            state.sim_instances.append(sim.setup(agents, seed))
    elif message_type == MESSAGE_TYPE_AGENT_ACTION:
        handle_agent_action(sender, msg, state)
    elif message_type == MESSAGE_TYPE_AGENT_MSG:
        logger.info("received AGENT_MSG on server sender=%s content=%s", sender, msg.get("content"))
    else:
        logger.warning("unknown message type sender=%s type=%s", sender, message_type)


def handle_agent_action(sender: str, msg: dict, state: State):
    agent_public_key = _extract_sender_public_key(sender, msg)
    sim_and_agent = state.find_sim_and_agent(agent_public_key)
    if sim_and_agent is None:
        logger.warning(
            "received AGENT_ACTION from unknown agent transport_sender=%s agent_public_key=%s",
            sender,
            agent_public_key,
        )
        return

    sim_instance, agent = sim_and_agent
    if getattr(sim_instance, "game_over", False):
        logger.info(
            "discard AGENT_ACTION for ended sim sim_id=%s sender=%s agent=%s",
            sim_instance.id,
            agent_public_key,
            agent.id,
        )
        return
    if not agent.alive:
        logger.info(
            "discard AGENT_ACTION from dead agent sim_id=%s sender=%s agent=%s",
            sim_instance.id,
            agent_public_key,
            agent.id,
        )
        return

    content = msg.get("content", msg)

    try:
        tick = _extract_action_tick(content, msg, sim_instance.iteration)
        action = Action.from_dict(_extract_action_payload(content, msg))
    except (TypeError, ValueError) as exc:
        logger.warning("invalid AGENT_ACTION sender=%s error=%s payload=%s", sender, exc, msg)
        return

    agent.queue_action(tick, action)
    logger.info(
        "queued action sim_id=%s sender=%s agent=%s tick=%s action=%s",
        sim_instance.id,
        agent_public_key,
        agent.id,
        tick,
        action.to_dict(),
    )


def _extract_sender_public_key(transport_sender: str, msg: dict) -> str:
    for container in (msg, msg.get("content")):
        if not isinstance(container, dict):
            continue
        for key in ("sender_public_key", "public_key", "agent_public_key"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return transport_sender


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
