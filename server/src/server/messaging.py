import asyncio
import json
import logging

from common import axl
from common.logging_config import demo_log
from common.protocol import (
    MESSAGE_TYPE_AGENT_ACTION,
    MESSAGE_TYPE_AGENT_MSG,
    MESSAGE_TYPE_AGENT_PROFILE,
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
        profile = _extract_agent_profile(msg, agent_public_key)
        state.add_to_queue(agent_public_key, profile)
        logger.info(
            "matchmaking join transport_sender=%s agent_public_key=%s agent_name=%s queue_size=%s sim_size=%s",
            sender,
            agent_public_key,
            profile.get("ens_name"),
            len(state.matchmaking_queue),
            state.sim_size,
        )
        if state.queue_ready():
            agents, seed, profiles = state.pick_new_sim_agents()
            logger.info("matchmaking ready agents=%s seed=%s profiles=%s", agents, seed, profiles)
            state.sim_instances.append(sim.setup(agents, seed, profiles))
    elif message_type == MESSAGE_TYPE_AGENT_PROFILE:
        agent_public_key = _extract_sender_public_key(sender, msg)
        profile = state.update_agent_profile(agent_public_key, _extract_agent_profile(msg, agent_public_key))
        logger.info(
            "agent profile update transport_sender=%s agent_public_key=%s agent_name=%s wallet=%s",
            sender,
            agent_public_key,
            profile.get("ens_name"),
            profile.get("wallet_address"),
        )
    elif message_type == MESSAGE_TYPE_AGENT_ACTION:
        handle_agent_action(sender, msg, state)
    elif message_type == MESSAGE_TYPE_AGENT_MSG:
        logger.info("received AGENT_MSG on server sender=%s content=%s", sender, msg.get("content"))
        agent_public_key = _extract_sender_public_key(sender, msg)
        content = msg.get("content")
        if isinstance(content, dict):
            text = content.get("message") or content.get("content") or ""
        else:
            text = content or ""
        if isinstance(text, str) and text.strip():
            profile = state.agent_profiles.get(agent_public_key, {})
            label = profile.get("ens_name") or agent_public_key[:8]
            demo_log(logger, "Chat %s -> server: %s", label, _one_line(text, 240))
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
        action_payloads, is_batch = _extract_action_payloads(content, msg)
    except (TypeError, ValueError) as exc:
        logger.warning("invalid AGENT_ACTION sender=%s error=%s payload=%s", sender, exc, msg)
        return

    if tick < sim_instance.iteration:
        logger.info(
            "discard stale AGENT_ACTION sim_id=%s sender=%s agent=%s tick=%s current_tick=%s",
            sim_instance.id,
            agent_public_key,
            agent.id,
            tick,
            sim_instance.iteration,
        )
        return

    if not sim_instance.accepts_action_submission(tick):
        logger.info(
            "discard AGENT_ACTION outside wait window sim_id=%s sender=%s agent=%s tick=%s current_tick=%s",
            sim_instance.id,
            agent_public_key,
            agent.id,
            tick,
            sim_instance.iteration,
        )
        return

    actions = []
    for action_payload in action_payloads:
        try:
            actions.append(Action.from_dict(action_payload))
        except (TypeError, ValueError) as exc:
            logger.warning(
                "invalid AGENT_ACTION item sender=%s error=%s payload=%s",
                sender,
                exc,
                action_payload,
            )
            if not is_batch:
                return

    if actions:
        agent.queue_actions(tick, actions)
    sim_instance.record_action_submission(agent, tick)
    logger.info(
        "queued action submission sim_id=%s sender=%s agent=%s tick=%s actions=%s",
        sim_instance.id,
        agent_public_key,
        agent.id,
        tick,
        [action.to_dict() for action in actions],
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


def _extract_agent_profile(msg: dict, agent_public_key: str) -> dict:
    content = msg.get("content")
    profile = {}
    if isinstance(content, dict):
        raw_profile = content.get("agent_profile") or content.get("profile")
        if isinstance(raw_profile, dict):
            profile.update(raw_profile)
        for key in (
            "ens_name",
            "wallet_address",
            "chain_id",
            "signature",
            "login_message",
            "profile_text_key",
            "profile_text_value",
            "profile_tx_hash",
            "resolver_address",
            "connected_at",
        ):
            if key in content and key not in profile:
                profile[key] = content[key]
    if isinstance(msg.get("agent_profile"), dict):
        profile.update(msg["agent_profile"])
    profile["agent_public_key"] = agent_public_key
    return profile


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


def _extract_action_payloads(content: object, msg: dict) -> tuple[list[object], bool]:
    if isinstance(content, dict):
        nested_actions = content.get("actions")
        if nested_actions is not None:
            if not isinstance(nested_actions, list):
                raise ValueError("Action batch payload must be a list")
            return nested_actions, True

        nested_action = content.get("action")
        if isinstance(nested_action, dict):
            return [nested_action], False
        if isinstance(nested_action, str):
            return [
                {
                    key: value
                    for key, value in content.items()
                    if key not in ("tick", "iteration")
                }
            ], False
        if "action_type" in content or "type" in content:
            return [
                {
                    key: value
                    for key, value in content.items()
                    if key not in ("tick", "iteration")
                }
            ], False

    nested_actions = msg.get("actions")
    if nested_actions is not None:
        if not isinstance(nested_actions, list):
            raise ValueError("Action batch payload must be a list")
        return nested_actions, True

    nested_action = msg.get("action")
    if nested_action is not None:
        return [nested_action], False

    return [msg], False


async def recv_loop(state: State):
    while True:
        received = axl.recv()
        if received is None:
            await asyncio.sleep(0.1)
            continue

        sender, msg = received
        await handle_message(sender, msg, state)


def _one_line(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."
