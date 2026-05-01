from __future__ import annotations

from . import config
from common import axl
import time
import json
import logging
from typing import Any

from .llm import get_chat_response, get_llm_response
from .state import State
from common.logging_config import demo_log

ACTION_KEYS = ("action", "target", "consumable", "item")
logger = logging.getLogger(__name__)


def client_loop(self_public_key: str, runtime: Any | None = None):
    state: State | None = None
    pending_agent_messages: list[dict[str, Any]] = []
    direct_chat_budget_by_tick: dict[int, float] = {}
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
            agent_message = _queue_agent_message(pending_agent_messages, sender, msg)
            if agent_message is not None and state is not None:
                _try_direct_chat_reply(
                    agent_message,
                    state,
                    self_public_key,
                    direct_chat_budget_by_tick,
                    runtime,
                )
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
        if runtime is not None:
            runtime.record_state(state.sim_state, pending_agent_messages)
        _prune_direct_chat_budget(direct_chat_budget_by_tick, state.tick)
        logger.info(
            "state update sim_id=%s tick=%s agent=%s valid_actions=%s incoming_agent_messages=%s",
            received_state.get("sim_id"),
            state.tick,
            received_state.get("agent"),
            len(state.get_valid_actions()),
            len(pending_agent_messages),
        )
        pending_agent_messages = []
        demo_log(logger, _demo_state_block(state))
        if _is_terminal_for_agent(state):
            results_block = _results_block(state)
            logger.info("simulation results\n%s", results_block)
            demo_log(logger, results_block)
            return

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
            demo_log(logger, "Reasoning: %s", _one_line(reasoning, 360))
        else:
            logger.info("llm reasoning tick=%s not returned", state.tick)

        # send response to server
        accepted = _send_llm_response(llm_response, state, self_public_key)
        if runtime is not None:
            runtime.record_decision(state.sim_state, llm_response, accepted)


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
) -> dict[str, Any] | None:
    content = msg.get("content", {})
    if isinstance(content, dict):
        message_text = content.get("message") or content.get("content") or ""
        tick = content.get("tick")
    else:
        message_text = str(content)
        tick = None

    if not isinstance(message_text, str) or not message_text.strip():
        return None

    agent_message = {
        "from": _agent_message_sender(sender, content),
        "tick": tick,
        "message": message_text.strip()[: config.MAX_AGENT_MESSAGE_CHARS],
    }
    pending_agent_messages.append(agent_message)
    logger.info("queued incoming agent message sender=%s tick=%s message=%s", sender, tick, message_text.strip())

    if len(pending_agent_messages) > config.AGENT_MESSAGE_HISTORY_LIMIT:
        del pending_agent_messages[:-config.AGENT_MESSAGE_HISTORY_LIMIT]

    return agent_message


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
) -> dict[str, Any]:
    actions = _filter_actions(
        llm_response.get("actions", []),
        state.get_valid_actions(),
        _agent_action_budget(state),
    )
    if not actions:
        wait_action = _default_wait_action(state.get_valid_actions())
        if wait_action is not None:
            actions = [wait_action]
            logger.info("using fallback wait action tick=%s", state.tick)

    tick = state.tick
    logger.info("accepted actions tick=%s actions=%s", tick, actions)
    demo_log(logger, "Decision: %s", _demo_actions(actions, state))
    for action in actions:
        _send_agent_action(action, tick, self_public_key)

    talk_recipients = _talk_recipients(actions)
    accepted_messages = _filter_agent_messages(llm_response.get("messages", []), talk_recipients)
    for message in accepted_messages:
        demo_log(
            logger,
            "You -> %s: %s",
            _agent_label_from_public_key(state, message["recipient"]),
            _one_line(message["content"], 240),
        )
        _send_agent_message(message["recipient"], message["content"], tick, self_public_key)

    return {"actions": actions, "messages": accepted_messages}


def _filter_actions(
    actions: list[dict[str, Any]],
    valid_actions: list[dict[str, Any]],
    action_budget: float,
) -> list[dict[str, Any]]:
    valid_action_specs = _valid_action_specs(valid_actions)
    remaining_budget = max(0.0, action_budget)

    selected_actions = []
    for raw_action in actions[: config.MAX_ACTIONS_PER_TICK]:
        action = _wire_action(raw_action)
        if action is None:
            logger.warning("skipping invalid LLM action raw_action=%s", raw_action)
            continue

        spec = valid_action_specs.get(action["action"])
        if spec is None:
            logger.warning("skipping unavailable LLM action action=%s raw_action=%s", action["action"], raw_action)
            continue

        required_fields = spec["required_fields"]
        missing_fields = [field for field in required_fields if field not in action]
        if missing_fields:
            logger.warning(
                "skipping LLM action missing required fields action=%s missing=%s raw_action=%s",
                action["action"],
                missing_fields,
                raw_action,
            )
            continue

        budget = spec["budget"]
        if budget > remaining_budget + 1e-9:
            logger.info(
                "skipping LLM action over client budget action=%s budget=%.2f remaining_budget=%.2f",
                action,
                budget,
                remaining_budget,
            )
            continue

        selected_actions.append(action)
        remaining_budget -= budget

    return selected_actions


def _valid_action_specs(valid_actions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    specs = {}
    for valid_action in valid_actions:
        action = _wire_action(valid_action)
        if action is None:
            continue

        required_fields = valid_action.get("required_fields", {})
        try:
            budget = float(valid_action.get("budget", 1.0))
        except (TypeError, ValueError):
            budget = 1.0
        if isinstance(required_fields, dict):
            field_names = set(required_fields)
        else:
            field_names = set()
        specs[action["action"]] = {"required_fields": field_names, "budget": max(0.0, budget)}
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


def _send_agent_action(action: dict[str, Any], tick: int | None, self_public_key: str) -> None:
    content = {
        "sender_public_key": self_public_key,
        "action": action,
    }
    if tick is not None:
        content["tick"] = tick

    message = {
        "protocol_version": config.PROTOCOL_VERSION,
        "message_type": config.MESSAGE_TYPE_AGENT_ACTION,
        "sender_public_key": self_public_key,
        "content": content,
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


def _try_direct_chat_reply(
    agent_message: dict[str, Any],
    state: State,
    self_public_key: str,
    direct_chat_budget_by_tick: dict[int, float],
    runtime: Any | None = None,
) -> None:
    if not config.DIRECT_AGENT_CHAT:
        return
    if _is_terminal_for_agent(state):
        return

    recipient = agent_message.get("from")
    if not isinstance(recipient, str) or not recipient:
        return

    talk_budget = _talk_to_budget(state)
    if talk_budget is None:
        logger.info("skip direct chat reply; talk_to is not currently valid")
        return

    if not _is_visible_agent(state, recipient):
        logger.info("skip direct chat reply; sender is not visible")
        return

    tick = state.tick
    spent = direct_chat_budget_by_tick.get(tick, 0.0)
    if spent + talk_budget > _agent_action_budget(state):
        demo_log(logger, "Chat budget spent for tick %s", tick)
        return

    if config.MAX_DIRECT_CHAT_REPLIES_PER_TICK <= spent / max(talk_budget, 0.0001):
        demo_log(logger, "Chat reply limit reached for tick %s", tick)
        return

    sender_label = _agent_label_from_public_key(state, recipient)
    demo_log(
        logger,
        "%s: %s",
        sender_label,
        _one_line(str(agent_message.get("message", "")), 240),
    )
    chat_response = get_chat_response(_direct_chat_prompt(state, agent_message))
    reasoning = chat_response.get("reasoning", "")
    if reasoning:
        demo_log(logger, "Chat reasoning: %s", _one_line(reasoning, 360))

    reply = chat_response.get("content", "").strip()
    if not reply:
        return

    _send_agent_action({"action": "talk_to", "target": recipient}, None, self_public_key)
    direct_chat_budget_by_tick[tick] = spent + talk_budget
    demo_log(logger, "You -> %s: %s", sender_label, _one_line(reply, 240))
    if runtime is not None:
        runtime.record_chat(
            state.sim_state,
            "outgoing",
            recipient,
            reply,
            {"mode": "direct_reply"},
        )
    _send_agent_message(recipient, reply, tick, self_public_key)


def _direct_chat_prompt(state: State, agent_message: dict[str, Any]) -> str:
    agent = _agent_state(state)
    sender = agent_message.get("from")
    sender_label = _agent_label_from_public_key(state, sender)
    return "\n".join(
        [
            f"Tick: {state.tick}",
            f"Temperature: {_number(state.sim_state.get('temp'))}C",
            (
                f"You: {_agent_label(agent)} at {_position_text(agent.get('position'))}; "
                f"health={_number(agent.get('health'))}, "
                f"hunger={_number(agent.get('hunger'))}, "
                f"thirst={_number(agent.get('thirst'))}, "
                f"warmth={_number(agent.get('warmth'))}, "
                f"carry={_number(agent.get('inventory_weight'))}/{_number(agent.get('carry_capacity'))}"
            ),
            f"Inventory: {_inventory_text(agent.get('inventory'))}",
            "Visible map:",
            _render_visible_map(state),
            f"Visible agents: {_visible_agents_text(state)}",
            f"Incoming from {sender_label}: {_one_line(str(agent_message.get('message', '')), config.MAX_AGENT_MESSAGE_CHARS)}",
            f"Reply to {sender_label}.",
        ]
    )


def _talk_to_budget(state: State) -> float | None:
    for action in state.get_valid_actions():
        if action.get("action") == "talk_to":
            try:
                return float(action.get("budget", config.CHAT_ACTION_BUDGET))
            except (TypeError, ValueError):
                return config.CHAT_ACTION_BUDGET
    return None


def _agent_action_budget(state: State) -> float:
    try:
        return float(_agent_state(state).get("action_budget", 1.0))
    except (TypeError, ValueError):
        return 1.0


def _is_visible_agent(state: State, public_key: str) -> bool:
    for tile in state.sim_state.get("visible_map", []):
        if not isinstance(tile, dict):
            continue
        for occupant in tile.get("occupants", []):
            if isinstance(occupant, dict) and occupant.get("public_key") == public_key and occupant.get("alive", True):
                return True
    return False


def _prune_direct_chat_budget(direct_chat_budget_by_tick: dict[int, float], current_tick: int) -> None:
    for tick in list(direct_chat_budget_by_tick):
        if tick < current_tick:
            del direct_chat_budget_by_tick[tick]


def _is_terminal_for_agent(state: State) -> bool:
    sim_status = state.sim_state.get("sim_status", {})
    if isinstance(sim_status, dict) and sim_status.get("game_over"):
        return True
    return _agent_state(state).get("alive") is False


def _results_block(state: State) -> str:
    agent = _agent_state(state)
    agent_id = agent.get("id")
    results = state.sim_state.get("results")
    sim_status = state.sim_state.get("sim_status", {})
    if not isinstance(results, dict):
        results = {
            "game_over": bool(isinstance(sim_status, dict) and sim_status.get("game_over")),
            "ended_tick": state.tick,
            "end_reason": "agent_dead" if agent.get("alive") is False else "finished",
            "winners": [],
            "leaderboard": state.sim_state.get("scoreboard", []),
            "deaths": [],
            "kills": [],
            "action_counts": {},
        }

    winners = results.get("winners", [])
    if agent.get("alive") is False:
        headline = "You died"
    elif agent_id in winners:
        headline = "You won"
    elif results.get("game_over"):
        headline = "Simulation ended"
    else:
        headline = "You are out"

    lines = [
        f"{headline} | tick {results.get('ended_tick', state.tick)} | {results.get('end_reason', '?')}",
        "Leaderboard:",
    ]

    leaderboard = results.get("leaderboard", [])
    if isinstance(leaderboard, list) and leaderboard:
        for row in leaderboard:
            if not isinstance(row, dict):
                continue
            status = "alive" if row.get("alive") else f"dead:{row.get('death_cause') or '?'}"
            lines.append(
                f"#{row.get('rank', '?')} A{row.get('agent_id', '?')} {status} "
                f"survived={row.get('survived_ticks', '?')} "
                f"kills={row.get('kills', 0)} actions={row.get('actions', 0)}"
            )
    else:
        lines.append("none")

    kills = results.get("kills", [])
    if isinstance(kills, list) and kills:
        lines.append("Kills:")
        for kill in kills:
            if not isinstance(kill, dict):
                continue
            lines.append(
                f"tick {kill.get('tick', '?')}: "
                f"A{kill.get('killer_id', '?')} killed A{kill.get('victim_id', '?')}"
            )

    deaths = results.get("deaths", [])
    if isinstance(deaths, list) and deaths:
        lines.append("Deaths:")
        for death in deaths:
            if not isinstance(death, dict):
                continue
            killed_by = death.get("killed_by")
            killer = "" if killed_by is None else f" by A{killed_by}"
            lines.append(
                f"tick {death.get('tick', '?')}: "
                f"A{death.get('agent_id', '?')} died{killer} ({death.get('cause', '?')})"
            )

    action_counts = results.get("action_counts", {})
    if isinstance(action_counts, dict) and action_counts:
        lines.append("Actions:")
        for agent_key in sorted(action_counts, key=lambda value: int(value) if str(value).isdigit() else str(value)):
            counts = action_counts.get(agent_key)
            if not isinstance(counts, dict):
                continue
            count_text = ", ".join(f"{name}={count}" for name, count in sorted(counts.items())) or "none"
            lines.append(f"A{agent_key}: {count_text}")

    return "\n".join(lines)


def _demo_state_block(state: State) -> str:
    agent = _agent_state(state)
    status = "" if agent.get("alive", True) else f" dead:{agent.get('death_cause') or '?'}"
    lines = [
        f"Tick {state.tick} | temp {_number(state.sim_state.get('temp'))}C",
        (
            f"You are {_agent_label(agent)} at {_position_text(agent.get('position'))} | "
            f"hp={_number(agent.get('health'))} "
            f"hunger={_number(agent.get('hunger'))} "
            f"thirst={_number(agent.get('thirst'))} "
            f"warmth={_number(agent.get('warmth'))} "
            f"carry={_number(agent.get('inventory_weight'))}/{_number(agent.get('carry_capacity'))}{status}"
        ),
        "Visible map:",
        _render_visible_map(state),
    ]

    if state.agent_messages:
        lines.append("Chat:")
        for message in state.agent_messages:
            lines.append(
                f"{_agent_label_from_public_key(state, message.get('from'))}: "
                f"{_one_line(str(message.get('message', '')), 240)}"
            )

    return "\n".join(lines)


def _render_visible_map(state: State) -> str:
    tiles = [
        tile for tile in state.sim_state.get("visible_map", [])
        if isinstance(tile, dict) and isinstance(tile.get("x"), int) and isinstance(tile.get("y"), int)
    ]
    if not tiles:
        return "(no visible tiles)"

    by_position = {(tile["x"], tile["y"]): tile for tile in tiles}
    xs = [tile["x"] for tile in tiles]
    ys = [tile["y"] for tile in tiles]
    lines = []
    for y in range(min(ys), max(ys) + 1):
        cells = []
        for x in range(min(xs), max(xs) + 1):
            tile = by_position.get((x, y))
            if tile is None:
                cells.append("  ")
                continue
            cells.append(_demo_tile_cell(state, tile))
        lines.append(" ".join(cells).rstrip())
    return "\n".join(lines)


def _demo_tile_cell(state: State, tile: dict[str, Any]) -> str:
    tile_type = str(tile.get("type", "?"))
    letter = tile_type[:1].upper() if tile_type else "?"
    has_self = False
    has_other = False
    self_id = _agent_state(state).get("id")
    for occupant in tile.get("occupants", []):
        if not isinstance(occupant, dict) or not occupant.get("alive", True):
            continue
        if occupant.get("id") == self_id:
            has_self = True
        else:
            has_other = True
    marker = "*" if has_other else "@" if has_self else "."
    return f"{letter}{marker}"


def _demo_actions(actions: list[dict[str, Any]], state: State) -> str:
    if not actions:
        return "wait"
    return ", ".join(_demo_action(action, state) for action in actions)


def _demo_action(action: dict[str, Any], state: State) -> str:
    action_name = str(action.get("action", "wait"))
    target = action.get("target")
    consumable = action.get("consumable")
    item = action.get("item")

    if action_name == "wait":
        return "wait"
    if action_name == "rest":
        return "rest"
    if action_name == "sleep":
        return "sleep"
    if action_name == "eat":
        return f"eat {_plain_value(consumable)}"
    if action_name == "drink":
        return f"drink {_plain_value(consumable)}"
    if action_name == "heal":
        return f"heal with {_plain_value(consumable)}"
    if action_name == "talk_to":
        return f"talk to {_agent_label_from_target(state, target)}"
    if action_name == "warmup":
        return f"warm up with {_plain_value(consumable)}"
    if action_name == "train":
        return "train"
    if action_name == "change_stance":
        return f"switch stance to {_target_text(target)}"
    if action_name == "move":
        return f"move to {_target_text(target)}"
    if action_name == "change_status":
        return f"switch status to {_target_text(target)}"
    if action_name == "create_shelter":
        return f"build shelter at {_target_text(target)}"
    if action_name == "attack":
        return f"attack {_agent_label_from_target(state, target)}"
    if action_name == "grow_food":
        return f"plant food at {_target_text(target)}"
    if action_name == "cook_food":
        return f"cook {_plain_value(consumable)} with {_plain_value(item)}"
    if action_name == "purify_water":
        return f"purify water with {_plain_value(item)}"
    if action_name == "steal":
        return f"steal at {_target_text(target)}"
    if action_name == "create_storage":
        return f"build storage at {_target_text(target)}"
    if action_name == "gather_wood":
        return f"gather wood at {_target_text(target)}"
    if action_name == "pick_resource":
        return f"pick up {_plain_value(consumable)}"
    if action_name == "fish":
        return f"fish at {_target_text(target)}"
    if action_name == "craft_fishing_rod":
        return "craft fishing rod"
    if action_name == "craft_trap":
        return "craft trap"
    if action_name == "set_trap":
        return "set trap"
    if action_name == "harvest_trap":
        return "harvest trap"
    if action_name == "trade":
        return (
            f"offer {_plain_value(consumable)} to {_agent_label_from_target(state, target)} "
            f"for {_plain_value(item)}"
        )
    return action_name.replace("_", " ")


def _agent_state(state: State) -> dict[str, Any]:
    agent = state.sim_state.get("agent", {})
    return agent if isinstance(agent, dict) else {}


def _agent_label(agent: dict[str, Any]) -> str:
    agent_id = agent.get("id")
    return f"A{agent_id}" if agent_id is not None else "A?"


def _agent_label_from_target(state: State, target: Any) -> str:
    if isinstance(target, dict):
        if "id" in target:
            return f"A{target['id']}"
        if isinstance(target.get("public_key"), str):
            return _agent_label_from_public_key(state, target["public_key"])
    if isinstance(target, int):
        return f"A{target}"
    if isinstance(target, str):
        return _agent_label_from_public_key(state, target)
    return "A?"


def _agent_label_from_public_key(state: State, public_key: Any) -> str:
    if not isinstance(public_key, str) or not public_key:
        return "A?"

    self_agent = _agent_state(state)
    if self_agent.get("public_key") == public_key:
        return _agent_label(self_agent)

    for tile in state.sim_state.get("visible_map", []):
        if not isinstance(tile, dict):
            continue
        for occupant in tile.get("occupants", []):
            if isinstance(occupant, dict) and occupant.get("public_key") == public_key:
                return _agent_label(occupant)
    return "A?"


def _visible_agents_text(state: State) -> str:
    self_id = _agent_state(state).get("id")
    seen: dict[Any, str] = {}
    for tile in state.sim_state.get("visible_map", []):
        if not isinstance(tile, dict):
            continue
        for occupant in tile.get("occupants", []):
            if not isinstance(occupant, dict) or not occupant.get("alive", True):
                continue
            if occupant.get("id") == self_id:
                continue
            label = _agent_label(occupant)
            seen[occupant.get("id", label)] = f"{label} at {_position_text(occupant.get('position'))}"
    return ", ".join(seen.values()) if seen else "none"


def _inventory_text(inventory: Any) -> str:
    if not isinstance(inventory, dict) or not inventory:
        return "empty"
    return ", ".join(f"{item}={amount}" for item, amount in inventory.items())


def _target_text(target: Any) -> str:
    if isinstance(target, dict) and "x" in target and "y" in target:
        return f"({target['x']},{target['y']})"
    return _plain_value(target)


def _position_text(position: Any) -> str:
    if isinstance(position, dict) and "x" in position and "y" in position:
        return f"({position['x']},{position['y']})"
    return "(?,?)"


def _plain_value(value: Any) -> str:
    if value is None:
        return "?"
    return str(value)


def _number(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.1f}"
    return "?"


def _one_line(text: str, limit: int) -> str:
    value = " ".join(text.split())
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."
