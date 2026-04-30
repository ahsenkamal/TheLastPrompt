from __future__ import annotations

from . import config
from common import axl
import time
import json
import logging
from typing import Any

from .llm import get_llm_response
from .state import State

ACTION_KEYS = ("action", "target", "consumable", "item")
logger = logging.getLogger(__name__)


def client_loop(self_public_key: str):
    state: State | None = None
    pending_agent_messages: list[dict[str, Any]] = []
    server_sender = config.SERVER_PEER_ID or config.SERVER_PUBLIC_KEY
    logger.info(
        "using server id=%s axl_match_prefix=%s",
        server_sender,
        config.AXL_PEER_ID_MATCH_PREFIX,
    )

    while True:
        # wait for state update from server
        received = axl.recv()
        if received is None:
            time.sleep(0.1)
            continue

        sender, msg = received
        msg = _decode_message(msg)
        if msg is None:
            continue

        if msg.get("protocol_version") != config.PROTOCOL_VERSION:
            logger.warning(
                "received unsupported protocol sender=%s version=%s",
                sender,
                msg.get("protocol_version"),
            )
            continue

        message_type = msg.get("message_type")
        logger.info("received message sender=%s type=%s", sender, message_type)
        if message_type == config.MESSAGE_TYPE_AGENT_MSG:
            _queue_agent_message(pending_agent_messages, sender, msg)
            continue

        if message_type != config.MESSAGE_TYPE_STATE_UPDATE:
            logger.warning("received unknown message type sender=%s type=%s", sender, message_type)
            continue

        if not _peer_ids_match(sender, server_sender):
            logger.warning(
                "received STATE_UPDATE from unexpected sender=%s expected=%s match_prefix=%s",
                sender,
                server_sender,
                config.AXL_PEER_ID_MATCH_PREFIX,
            )
            continue

        if sender != server_sender:
            logger.info(
                "accepted server sender by AXL prefix sender=%s expected=%s prefix=%s",
                sender,
                server_sender,
                config.AXL_PEER_ID_MATCH_PREFIX,
            )

        # update client state
        received_state = msg.get("content")
        if not isinstance(received_state, dict):
            logger.warning("received STATE_UPDATE without object content")
            continue

        if state is None:
            state = State(received_state)
        else:
            state.update(received_state)
        state.set_agent_messages(pending_agent_messages)
        logger.info(
            "state update sim_id=%s tick=%s agent=%s valid_actions=%s incoming_agent_messages=%s",
            received_state.get("sim_id"),
            state.tick,
            received_state.get("agent"),
            len(state.get_valid_actions()),
            len(pending_agent_messages),
        )
        pending_agent_messages = []

        # create prompt for user
        final_prompt = config.BASE_PROMPT + "\n\n" + config.USER_PROMPT + "\n\n" + state.get_state_description()
        logger.debug("final prompt tick=%s\n%s", state.tick, final_prompt)

        # get llm response
        llm_response = get_llm_response(final_prompt)
        logger.info(
            "llm decision tick=%s actions=%s messages=%s",
            state.tick,
            llm_response.get("actions", []),
            llm_response.get("messages", []),
        )
        reasoning = llm_response.get("reasoning")
        if isinstance(reasoning, str) and reasoning:
            logger.info("llm reasoning tick=%s\n%s", state.tick, reasoning)
        else:
            logger.info("llm reasoning tick=%s not returned", state.tick)

        # send response to server
        _send_llm_response(llm_response, state, self_public_key)


def _decode_message(raw_msg: str) -> dict[str, Any] | None:
    try:
        msg = json.loads(raw_msg)
    except json.JSONDecodeError as exc:
        logger.warning("received invalid JSON message error=%s raw=%s", exc, raw_msg)
        return None

    if not isinstance(msg, dict):
        logger.warning("received non-object JSON message raw=%s", raw_msg)
        return None
    return msg


def _peer_ids_match(actual: str, expected: str) -> bool:
    if actual == expected:
        return True

    prefix_len = config.AXL_PEER_ID_MATCH_PREFIX
    if prefix_len <= 0:
        return False
    if len(actual) < prefix_len or len(expected) < prefix_len:
        return False

    return actual[:prefix_len].lower() == expected[:prefix_len].lower()


def _queue_agent_message(
    pending_agent_messages: list[dict[str, Any]],
    sender: str,
    msg: dict[str, Any],
) -> None:
    content = msg.get("content", {})
    if isinstance(content, dict):
        message_text = content.get("message") or content.get("content") or ""
        tick = content.get("tick")
    else:
        message_text = str(content)
        tick = None

    if not isinstance(message_text, str) or not message_text.strip():
        return

    pending_agent_messages.append(
        {
            "from": _agent_message_sender(sender, content),
            "tick": tick,
            "message": message_text.strip()[: config.MAX_AGENT_MESSAGE_CHARS],
        }
    )
    logger.info("queued incoming agent message sender=%s tick=%s message=%s", sender, tick, message_text.strip())

    if len(pending_agent_messages) > config.AGENT_MESSAGE_HISTORY_LIMIT:
        del pending_agent_messages[:-config.AGENT_MESSAGE_HISTORY_LIMIT]


def _agent_message_sender(transport_sender: str, content: object) -> str:
    if isinstance(content, dict):
        sender = content.get("from") or content.get("sender_public_key") or content.get("public_key")
        if isinstance(sender, str) and sender.strip():
            return sender.strip()
    return transport_sender


def _send_llm_response(
    llm_response: dict[str, Any],
    state: State,
    self_public_key: str,
) -> None:
    actions = _filter_actions(llm_response.get("actions", []), state.get_valid_actions())
    if not actions:
        wait_action = _default_wait_action(state.get_valid_actions())
        if wait_action is not None:
            actions = [wait_action]
            logger.info("using fallback wait action tick=%s", state.tick)

    tick = state.tick
    logger.info("accepted actions tick=%s actions=%s", tick, actions)
    for action in actions:
        _send_agent_action(action, tick, self_public_key)

    talk_recipients = _talk_recipients(actions)
    for message in _filter_agent_messages(llm_response.get("messages", []), talk_recipients):
        _send_agent_message(message["recipient"], message["content"], tick, self_public_key)


def _filter_actions(
    actions: list[dict[str, Any]],
    valid_actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    valid_action_specs = _valid_action_specs(valid_actions)

    selected_actions = []
    for raw_action in actions[: config.MAX_ACTIONS_PER_TICK]:
        action = _wire_action(raw_action)
        if action is None:
            logger.warning("skipping invalid LLM action raw_action=%s", raw_action)
            continue

        required_fields = valid_action_specs.get(action["action"])
        if required_fields is None:
            logger.warning("skipping unavailable LLM action action=%s raw_action=%s", action["action"], raw_action)
            continue

        missing_fields = [field for field in required_fields if field not in action]
        if missing_fields:
            logger.warning(
                "skipping LLM action missing required fields action=%s missing=%s raw_action=%s",
                action["action"],
                missing_fields,
                raw_action,
            )
            continue

        selected_actions.append(action)

    return selected_actions


def _valid_action_specs(valid_actions: list[dict[str, Any]]) -> dict[str, set[str]]:
    specs = {}
    for valid_action in valid_actions:
        action = _wire_action(valid_action)
        if action is None:
            continue

        required_fields = valid_action.get("required_fields", {})
        if isinstance(required_fields, dict):
            specs[action["action"]] = set(required_fields)
        else:
            specs[action["action"]] = set()
    return specs


def _filter_agent_messages(
    messages: list[dict[str, Any]],
    talk_recipients: set[str],
) -> list[dict[str, str]]:
    selected_messages = []
    for raw_message in messages[: config.MAX_AGENT_MESSAGES_PER_TICK]:
        recipient = raw_message.get("recipient")
        content = raw_message.get("content")
        if not isinstance(recipient, str) or recipient not in talk_recipients:
            logger.warning("skipping agent message without matching talk_to action raw_message=%s", raw_message)
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        selected_messages.append(
            {
                "recipient": recipient,
                "content": content.strip()[: config.MAX_AGENT_MESSAGE_CHARS],
            }
        )
    return selected_messages


def _send_agent_action(action: dict[str, Any], tick: int, self_public_key: str) -> None:
    message = {
        "protocol_version": config.PROTOCOL_VERSION,
        "message_type": config.MESSAGE_TYPE_AGENT_ACTION,
        "sender_public_key": self_public_key,
        "content": {
            "tick": tick,
            "sender_public_key": self_public_key,
            "action": action,
        },
    }
    axl.send(message, config.SERVER_PUBLIC_KEY)
    logger.info("sent AGENT_ACTION tick=%s action=%s server=%s", tick, action, config.SERVER_PUBLIC_KEY)


def _send_agent_message(recipient: str, content: str, tick: int, self_public_key: str) -> None:
    message = {
        "protocol_version": config.PROTOCOL_VERSION,
        "message_type": config.MESSAGE_TYPE_AGENT_MSG,
        "content": {
            "tick": tick,
            "from": self_public_key,
            "message": content,
        },
    }
    axl.send(message, recipient)
    logger.info("sent AGENT_MSG tick=%s recipient=%s message=%s", tick, recipient, content)


def _wire_action(raw_action: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw_action, dict):
        return None

    action_name = raw_action.get("action") or raw_action.get("action_type") or raw_action.get("type")
    if not isinstance(action_name, str) or not action_name.strip():
        return None

    action: dict[str, Any] = {"action": action_name.strip().lower()}
    for key in ACTION_KEYS[1:]:
        if key in raw_action and raw_action[key] is not None:
            action[key] = raw_action[key]
    return action


def _default_wait_action(valid_actions: list[dict[str, Any]]) -> dict[str, Any] | None:
    for action in valid_actions:
        wire_action = _wire_action(action)
        if wire_action is not None and wire_action.get("action") == "wait":
            return wire_action
    return None


def _talk_recipients(actions: list[dict[str, Any]]) -> set[str]:
    recipients = set()
    for action in actions:
        if action.get("action") != "talk_to":
            continue
        target = action.get("target")
        if isinstance(target, str):
            recipients.add(target)
        elif isinstance(target, dict) and isinstance(target.get("public_key"), str):
            recipients.add(target["public_key"])
    return recipients
