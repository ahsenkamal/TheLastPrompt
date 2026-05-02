from __future__ import annotations

from . import config
from common import axl
from copy import deepcopy
import time
import json
import logging
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from typing import Any

from .llm import create_action_log_payload, get_chat_response, get_llm_response, get_plan_response, get_summary_response
from .state import State
from common.identity import agent_display_name, profile_matches_name
from common.logging_config import demo_log, is_demo_logging

ACTION_KEYS = ("action", "target", "consumable", "item")
LABEL_TARGET_ACTIONS = {"attack", "trade", "talk_to"}
ReceivedMessage = tuple[str, str]
logger = logging.getLogger(__name__)


def client_loop(self_public_key: str, runtime: Any | None = None):
    inbox = AxlInbox()
    inbox.start()
    try:
        _client_loop(self_public_key, runtime, inbox)
    finally:
        inbox.stop()


class AxlInbox:
    def __init__(self, poll_interval: float = 0.1):
        self._poll_interval = poll_interval
        self._messages: Queue[ReceivedMessage] = Queue()
        self._stop = Event()
        self._thread = Thread(target=self._run, name="axl-recv", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)

    def get(self, timeout: float | None = None) -> ReceivedMessage | None:
        try:
            return self._messages.get(timeout=timeout)
        except Empty:
            return None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                received = axl.recv()
            except Exception:
                logger.exception("AXL receive failed")
                self._stop.wait(self._poll_interval)
                continue

            if received is None:
                self._stop.wait(self._poll_interval)
                continue

            self._messages.put(received)


def _client_loop(self_public_key: str, runtime: Any | None, inbox: AxlInbox):
    state: State | None = None
    pending_agent_messages: list[dict[str, Any]] = []
    recent_agent_messages: list[dict[str, Any]] = []
    talk_summary_history: list[dict[str, Any]] = []
    direct_chat_budget_by_tick: dict[int, float] = {}
    deferred_received: ReceivedMessage | None = None
    server_sender = config.SERVER_PEER_ID or config.SERVER_PUBLIC_KEY
    logger.info(
        "using server id=%s axl_match_prefix=%s",
        server_sender,
        config.AXL_PEER_ID_MATCH_PREFIX,
    )

    while True:
        if runtime is not None:
            for profile in runtime.pop_profile_updates():
                _send_agent_profile(profile, self_public_key)

        # wait for state update from server
        if deferred_received is not None:
            received = deferred_received
            deferred_received = None
        else:
            received = inbox.get(timeout=0.1)
        if received is None:
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
            if agent_message is not None:
                demo_log(
                    logger,
                    "%s -> You: %s",
                    _chat_peer_label(state, agent_message["from"]),
                    _one_line(agent_message["message"], 240),
                )
            if agent_message is not None:
                _append_chat_context(
                    recent_agent_messages,
                    {
                        "direction": "incoming",
                        "from": agent_message["from"],
                        "tick": agent_message.get("tick"),
                        "message": agent_message["message"],
                    },
                )
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
        turn_messages = list(pending_agent_messages)
        state.set_agent_messages(turn_messages, recent_agent_messages)
        if runtime is not None:
            runtime.record_state(state.sim_state, turn_messages)
        _prune_direct_chat_budget(direct_chat_budget_by_tick, state.tick)
        logger.info(
            "state update sim_id=%s tick=%s agent=%s valid_actions=%s incoming_agent_messages=%s",
            received_state.get("sim_id"),
            state.tick,
            received_state.get("agent"),
            len(state.get_valid_actions()),
            len(turn_messages),
        )
        pending_agent_messages = []
        demo_log(logger, _demo_state_block(state))
        if _is_terminal_for_agent(state):
            results_block = _results_block(state)
            logger.info("simulation results\n%s", results_block)
            demo_log(logger, results_block)
            return

        talk_result = _run_talk_phase(
            state,
            self_public_key,
            turn_messages,
            recent_agent_messages,
            runtime,
            inbox,
        )
        deferred_received = talk_result.get("deferred_received")
        if deferred_received is not None:
            continue

        state.set_agent_messages(
            [],
            [],
            _talk_phase_context(talk_result, state, talk_summary_history),
        )

        # create prompt for user
        final_prompt = config.BASE_PROMPT + "\n\n" + config.USER_PROMPT + "\n\n" + _llm_state_description(state)
        logger.debug("final prompt tick=%s\n%s", state.tick, final_prompt)

        # get llm response
        llm_response = get_llm_response(final_prompt)
        _record_action_llm_artifact(state, create_action_log_payload(final_prompt), llm_response)
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
        action_accepted = _send_llm_response(
            llm_response,
            state,
            self_public_key,
            action_budget=talk_result["action_budget"],
            allow_talk=not config.TALK_PHASE_ENABLED,
            prefix_actions=talk_result["actions"],
            talk_budget=talk_result["talk_budget"],
            talk_budget_spent=talk_result["talk_budget_spent"],
        )
        accepted = {
            "actions": action_accepted["actions"],
            "messages": talk_result["messages"] + action_accepted["messages"],
            "talk_summary": talk_result["talk_summary"],
            "phase_budgets": {
                "talk_budget": talk_result["talk_budget"],
                "talk_budget_spent": talk_result["talk_budget_spent"],
                "action_budget": talk_result["action_budget"],
            },
        }
        for message in action_accepted["messages"]:
            _append_chat_context(
                recent_agent_messages,
                {
                    "direction": "outgoing",
                    "to": message["recipient"],
                    "tick": state.tick,
                    "message": message["content"],
                },
            )
        if runtime is not None:
            runtime.record_decision(state.sim_state, llm_response, accepted)
        _append_talk_summary_history(talk_summary_history, state.tick, talk_result["talk_summary"])


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


def _append_chat_context(chat_context: list[dict[str, Any]], message: dict[str, Any]) -> None:
    chat_context.append(message)
    if len(chat_context) > config.CHAT_CONTEXT_LIMIT:
        del chat_context[:-config.CHAT_CONTEXT_LIMIT]


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _run_talk_phase(
    state: State,
    self_public_key: str,
    turn_messages: list[dict[str, Any]],
    recent_agent_messages: list[dict[str, Any]],
    runtime: Any | None,
    inbox: AxlInbox,
) -> dict[str, Any]:
    action_budget = _agent_action_budget(state)
    talk_budget_limit = max(0.0, config.TALK_BUDGET)
    result: dict[str, Any] = {
        "talk_summary": "",
        "actions": [],
        "messages": [],
        "talk_budget": talk_budget_limit,
        "talk_budget_spent": 0.0,
        "action_budget": action_budget,
        "deferred_received": None,
    }

    talk_recipients = _valid_talk_recipients(state)
    demo_log(
        logger,
        "Talk phase: enabled=%s recipients=%s budget=%.2f seconds=%.0f incoming=%s recent=%s",
        config.TALK_PHASE_ENABLED,
        len(talk_recipients),
        talk_budget_limit,
        config.TALK_PHASE_SECONDS,
        len(turn_messages),
        len(recent_agent_messages),
    )

    if not config.TALK_PHASE_ENABLED:
        demo_log(logger, "Talk phase skipped: disabled")
        return result
    if talk_budget_limit <= 0:
        demo_log(logger, "Talk phase skipped: talk budget is 0")
        return result

    phase_messages = list(turn_messages)
    prefetched_received: list[ReceivedMessage] = []
    if not talk_recipients and not turn_messages:
        received = inbox.get(timeout=0.0)
        if received is None:
            demo_log(logger, "Talk phase skipped: no visible talk recipients and no incoming messages")
            return result
        prefetched_received.append(received)

    talk_budget = _talk_to_budget(state) or config.CHAT_ACTION_BUDGET
    sent_messages: list[dict[str, str]] = []
    sent_recipients = set()
    sent_counts_by_peer: dict[str, int] = {}
    incoming_counts_by_peer = _incoming_counts_by_peer(phase_messages)
    pending_reply_peers = {
        message["from"]
        for message in phase_messages
        if isinstance(message.get("from"), str) and message["from"] in talk_recipients
    }
    waiting_for_reply_peers: set[str] = set()
    tie_break_wait_peers: set[str] = set()
    closed_peers: set[str] = set()
    decision_needed = True
    finish_talk_phase = False
    deadline = time.monotonic() + max(0.0, config.TALK_PHASE_SECONDS)

    def consume_received(received: ReceivedMessage) -> bool:
        nonlocal decision_needed, finish_talk_phase

        sender, raw_msg = received
        msg = _decode_message(raw_msg)
        if msg is None:
            return False

        if msg.get("protocol_version") != config.PROTOCOL_VERSION:
            logger.warning(
                "received unsupported protocol during talk phase sender=%s version=%s",
                sender,
                msg.get("protocol_version"),
            )
            return False

        if msg.get("message_type") != config.MESSAGE_TYPE_AGENT_MSG:
            result["deferred_received"] = received
            return True

        agent_message = _record_talk_phase_message(
            state,
            sender,
            msg,
            turn_messages,
            recent_agent_messages,
            phase_messages,
            runtime,
        )
        if agent_message is None:
            return False

        peer = agent_message["from"]
        message_tick = agent_message.get("tick")
        if peer not in talk_recipients or (message_tick is not None and message_tick != state.tick):
            return False

        if _incoming_closes_conversation(peer, agent_message["message"], phase_messages):
            closed_peers.add(peer)
            waiting_for_reply_peers.discard(peer)
            pending_reply_peers.discard(peer)
            tie_break_wait_peers.discard(peer)
            finish_talk_phase = not pending_reply_peers and not waiting_for_reply_peers
            demo_log(
                logger,
                "Talk phase: %s closed the conversation; no reply needed",
                _agent_label_from_public_key(state, peer),
            )
            return False

        incoming_counts_by_peer[peer] = incoming_counts_by_peer.get(peer, 0) + 1
        if _should_wait_for_peer_turn(
            state,
            peer,
            sent_counts_by_peer,
            incoming_counts_by_peer,
            tie_break_wait_peers,
        ):
            waiting_for_reply_peers.add(peer)
            return False

        waiting_for_reply_peers.discard(peer)
        pending_reply_peers.add(peer)
        decision_needed = True
        return False

    while True:
        while prefetched_received:
            if consume_received(prefetched_received.pop(0)):
                return result

        while True:
            received = inbox.get(timeout=0.0)
            if received is None:
                break
            if consume_received(received):
                return result

        if finish_talk_phase:
            break

        remaining_talk_budget = max(0.0, talk_budget_limit - len(sent_messages) * talk_budget)
        can_send_more = (
            len(sent_messages) < config.MAX_TALK_MESSAGES_PER_TICK
            and remaining_talk_budget + 1e-9 >= talk_budget
        )

        if decision_needed and can_send_more:
            allowed_recipients = _talk_decision_recipients(
                talk_recipients,
                pending_reply_peers,
                waiting_for_reply_peers,
                tie_break_wait_peers,
                closed_peers,
            )
            if allowed_recipients:
                pending_replies_for_decision = set(pending_reply_peers)
                talk_prompt = _talk_phase_prompt(
                    state,
                    phase_messages,
                    recent_agent_messages,
                    remaining_talk_budget,
                    allowed_recipients,
                    pending_reply_peers,
                    waiting_for_reply_peers,
                    tie_break_wait_peers,
                )
                demo_log(logger, "Talk LLM prompt: chars=%s est_tokens=%s", len(talk_prompt), _estimate_tokens(talk_prompt))
                talk_response = get_plan_response(talk_prompt)
                max_messages_remaining = config.MAX_TALK_MESSAGES_PER_TICK - len(sent_messages)
                talk_messages = _filter_talk_messages(
                    talk_response.get("messages", []),
                    state,
                    remaining_talk_budget,
                    allowed_recipients=allowed_recipients,
                    max_messages=max_messages_remaining,
                )
                if not talk_messages:
                    if pending_replies_for_decision:
                        closed_peers.update(pending_replies_for_decision)
                        waiting_for_reply_peers.difference_update(pending_replies_for_decision)
                        finish_talk_phase = not waiting_for_reply_peers
                        demo_log(
                            logger,
                            "Talk phase: LLM ended conversation with %s",
                            _peer_list_text(state, pending_replies_for_decision),
                        )
                    else:
                        demo_log(logger, "Talk phase: no outgoing messages right now; listening")
                for message in talk_messages:
                    _send_talk_phase_message(
                        message,
                        state,
                        self_public_key,
                        recent_agent_messages,
                        phase_messages,
                        runtime,
                    )
                    recipient = message["recipient"]
                    sent_messages.append(message)
                    sent_recipients.add(recipient)
                    sent_counts_by_peer[recipient] = sent_counts_by_peer.get(recipient, 0) + 1
                    waiting_for_reply_peers.add(recipient)
            pending_reply_peers.clear()
            decision_needed = False

        if config.TALK_PHASE_SECONDS <= 0 or time.monotonic() >= deadline:
            break

        timeout = min(0.1, max(0.0, deadline - time.monotonic()))
        received = inbox.get(timeout=timeout)
        if received is None:
            continue

        if consume_received(received):
            return result

    result["actions"] = [{"action": "talk_to", "target": recipient} for recipient in sorted(sent_recipients)]
    result["messages"] = sent_messages
    result["talk_budget_spent"] = min(talk_budget_limit, len(sent_messages) * talk_budget)
    result["talk_summary"] = _summarize_talk_phase(state, phase_messages)
    if result["talk_summary"]:
        demo_log(logger, "Talk summary: %s", _one_line(result["talk_summary"], 360))
    return result


def _talk_phase_context(
    talk_result: dict[str, Any],
    state: State,
    talk_summary_history: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "summary": talk_result.get("talk_summary", ""),
        "previous_summaries": _previous_talk_summaries(talk_summary_history, state.tick),
        "sent_messages_count": len(talk_result.get("messages", [])),
        "talk_budget": talk_result.get("talk_budget", 0),
        "talk_budget_spent": talk_result.get("talk_budget_spent", 0),
        "action_budget": talk_result.get("action_budget", _agent_action_budget(state)),
    }


def _previous_talk_summaries(history: list[dict[str, Any]], current_tick: int) -> list[dict[str, Any]]:
    history_ticks = max(0, config.TALK_SUMMARY_HISTORY_TICKS)
    if history_ticks <= 0:
        return []

    first_tick = current_tick - history_ticks
    return [
        dict(entry)
        for entry in history
        if first_tick <= int(entry.get("tick", -1)) < current_tick
    ]


def _append_talk_summary_history(history: list[dict[str, Any]], tick: int, summary: str) -> None:
    history_ticks = max(0, config.TALK_SUMMARY_HISTORY_TICKS)
    if history_ticks <= 0:
        history.clear()
        return

    summary = " ".join(str(summary or "").split())
    if summary:
        history.append({"tick": tick, "summary": summary})

    first_tick = tick - history_ticks + 1
    while history and int(history[0].get("tick", -1)) < first_tick:
        del history[0]


def _record_talk_phase_message(
    state: State,
    sender: str,
    msg: dict[str, Any],
    turn_messages: list[dict[str, Any]],
    recent_agent_messages: list[dict[str, Any]],
    phase_messages: list[dict[str, Any]],
    runtime: Any | None,
) -> dict[str, Any] | None:
    agent_message = _queue_agent_message(turn_messages, sender, msg)
    if agent_message is None:
        return None

    _append_chat_context(
        recent_agent_messages,
        {
            "direction": "incoming",
            "from": agent_message["from"],
            "tick": agent_message.get("tick"),
            "message": agent_message["message"],
        },
    )
    phase_messages.append(
        {
            "direction": "incoming",
            "from": agent_message["from"],
            "tick": agent_message.get("tick"),
            "message": agent_message["message"],
        }
    )
    demo_log(
        logger,
        "%s: %s",
        _agent_label_from_public_key(state, agent_message["from"]),
        _one_line(agent_message["message"], 240),
    )
    if runtime is not None:
        runtime.record_chat(
            state.sim_state,
            "incoming",
            agent_message["from"],
            agent_message["message"],
            {"mode": "talk_phase"},
        )
    return agent_message


def _incoming_closes_conversation(peer: str, incoming_text: str, phase_messages: list[dict[str, Any]]) -> bool:
    text = _normalized_chat_text(incoming_text)
    if not text or "?" in incoming_text:
        return False

    last_outgoing = _last_outgoing_to_peer(peer, phase_messages)
    if last_outgoing is not None and _is_acknowledgement_text(text):
        return True

    if _is_peer_commitment_text(text):
        return True

    return False


def _last_outgoing_to_peer(peer: str, phase_messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(phase_messages[:-1]):
        if message.get("direction") == "outgoing" and message.get("to") == peer:
            return message
    return None


def _is_acknowledgement_text(text: str) -> bool:
    ack_phrases = (
        "go ahead",
        "sounds good",
        "that works",
        "works for me",
        "understood",
        "got it",
        "do that",
        "proceed",
        "thank you",
        "thanks",
        "agreed",
        "agree",
        "roger",
        "deal",
    )
    if any(phrase in text for phrase in ack_phrases):
        return True

    words = set(text.split())
    return bool(words & {"ok", "okay", "yes", "yep", "sure", "fine"})


def _is_peer_commitment_text(text: str) -> bool:
    if _looks_like_request(text):
        return False

    commitment_phrases = ("i'll", "ill", "i will", "i am going to", "i'm going to")
    if not any(phrase in text for phrase in commitment_phrases):
        return False

    words = set(text.split())
    cooperative_actions = {
        "gather",
        "gathering",
        "pick",
        "collect",
        "harvest",
        "move",
        "get",
        "bring",
        "take",
        "handle",
        "work",
        "fish",
        "craft",
        "build",
        "cook",
        "purify",
    }
    return bool(words & cooperative_actions)


def _looks_like_request(text: str) -> bool:
    request_phrases = (
        "can you",
        "could you",
        "would you",
        "will you",
        "do you",
        "should we",
        "should i",
        "want to",
        "want me",
        "if you want",
        "need you",
        "i need",
        "we need",
        "please",
        "let's",
        "lets",
    )
    return any(phrase in text for phrase in request_phrases)


def _normalized_chat_text(text: str) -> str:
    return " ".join(
        "".join(char.lower() if char.isalnum() or char in {"'", " "} else " " for char in text).split()
    )


def _send_talk_phase_message(
    message: dict[str, str],
    state: State,
    self_public_key: str,
    recent_agent_messages: list[dict[str, Any]],
    phase_messages: list[dict[str, Any]],
    runtime: Any | None,
) -> None:
    recipient = message["recipient"]
    content = message["content"]
    demo_log(
        logger,
        "You -> %s: %s",
        _agent_label_from_public_key(state, recipient),
        _one_line(content, 240),
    )
    _send_agent_message(recipient, content, state.tick, self_public_key)
    _append_chat_context(
        recent_agent_messages,
        {
            "direction": "outgoing",
            "to": recipient,
            "tick": state.tick,
            "message": content,
        },
    )
    phase_messages.append(
        {
            "direction": "outgoing",
            "to": recipient,
            "tick": state.tick,
            "message": content,
        }
    )
    if runtime is not None:
        runtime.record_chat(
            state.sim_state,
            "outgoing",
            recipient,
            content,
            {"mode": "talk_phase"},
        )


def _incoming_counts_by_peer(messages: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for message in messages:
        peer = message.get("from")
        if isinstance(peer, str):
            counts[peer] = counts.get(peer, 0) + 1
    return counts


def _talk_decision_recipients(
    talk_recipients: set[str],
    pending_reply_peers: set[str],
    waiting_for_reply_peers: set[str],
    tie_break_wait_peers: set[str],
    closed_peers: set[str],
) -> set[str]:
    recipients = set(pending_reply_peers) - tie_break_wait_peers - closed_peers
    for recipient in talk_recipients:
        if recipient in waiting_for_reply_peers or recipient in tie_break_wait_peers or recipient in closed_peers:
            continue
        recipients.add(recipient)
    return recipients


def _should_wait_for_peer_turn(
    state: State,
    peer: str,
    sent_counts_by_peer: dict[str, int],
    incoming_counts_by_peer: dict[str, int],
    tie_break_wait_peers: set[str],
) -> bool:
    if peer in tie_break_wait_peers:
        tie_break_wait_peers.remove(peer)
        return False

    if sent_counts_by_peer.get(peer, 0) <= 0 or incoming_counts_by_peer.get(peer, 0) != 1:
        return False

    self_id = _agent_state(state).get("id")
    peer_id = _agent_id_from_public_key(state, peer)
    if not isinstance(self_id, int) or not isinstance(peer_id, int) or self_id <= peer_id:
        return False

    tie_break_wait_peers.add(peer)
    demo_log(
        logger,
        "Talk phase: simultaneous opener with %s; %s waits for lower-id reply",
        _agent_label_from_public_key(state, peer),
        _agent_label(_agent_state(state)),
    )
    return True


def _talk_phase_prompt(
    state: State,
    phase_messages: list[dict[str, Any]],
    recent_agent_messages: list[dict[str, Any]],
    talk_budget_remaining: float,
    allowed_recipients: set[str],
    pending_reply_peers: set[str],
    waiting_for_reply_peers: set[str],
    tie_break_wait_peers: set[str],
) -> str:
    agent = _agent_state(state)
    talk_budget = _talk_to_budget(state) or config.CHAT_ACTION_BUDGET
    return "\n".join(
        [
            "Talk phase: choose whether to speak right now in an ongoing multi-agent conversation.",
            f"Tick: {state.tick}",
            f"Phase: {state.sim_state.get('phase', 'day')}",
            f"Temperature: {_number(state.sim_state.get('temp'))}C",
            f"Remaining talk budget: {talk_budget_remaining:.2f}; talk_to cost per message: {talk_budget:.2f}; max messages this tick: {config.MAX_TALK_MESSAGES_PER_TICK}",
            "Action choices are decided later; this phase only sends chat.",
            "Conversation protocol:",
            "- You may speak to multiple allowed recipients, one short message per recipient.",
            "- You may also stay silent by returning an empty messages array.",
            "- If you just sent a peer a message, wait for that peer before sending another message to them.",
            "- If you and a peer both opened at the same time, the higher simulation id waits and the lower simulation id replies first.",
            "- End the conversation by returning an empty messages array when the peer acknowledged, agreed, gave permission, or committed to an action and there is no new question.",
            "- Do not repeat a commitment you already made, such as saying you will gather after the peer already said to go ahead.",
            (
                f"You: {_agent_label(agent)} at {_position_text(agent.get('position'))}; "
                f"health={_number(agent.get('health'))}, hunger={_number(agent.get('hunger'))}, "
                f"thirst={_number(agent.get('thirst'))}, warmth={_number(agent.get('warmth'))}, "
                f"carry={_number(agent.get('inventory_weight'))}/{_number(agent.get('carry_capacity'))}"
            ),
            f"Inventory: {_inventory_text(agent.get('inventory'))}",
            f"Current tile resources: {_current_tile_resources_text(state)}",
            "Visible map:",
            _render_visible_map(state),
            f"Visible agents: {_visible_agents_text(state)}",
            "Use only listed agent names such as ENS names for chat recipients and social action targets.",
            f"All talk recipients: {_talk_recipients_text(state)}",
            f"Allowed recipients now: {_peer_list_text(state, allowed_recipients)}",
            f"Peers waiting for your reply: {_peer_list_text(state, pending_reply_peers)}",
            f"Peers you are waiting on: {_peer_list_text(state, waiting_for_reply_peers)}",
            f"Peers blocked by agent-id tie-break: {_peer_list_text(state, tie_break_wait_peers)}",
            "Talk transcript this phase:",
            _chat_messages_text(phase_messages, state),
            f"Recent chat: {_chat_messages_text(recent_agent_messages, state)}",
        ]
    )


def _summarize_talk_phase(state: State, phase_messages: list[dict[str, Any]]) -> str:
    if not phase_messages:
        return ""
    fallback = _fallback_talk_summary(state, phase_messages)
    response = get_summary_response(_talk_summary_prompt(state, phase_messages))
    summary = response.get("summary", "").strip()
    return summary or fallback


def _talk_summary_prompt(state: State, phase_messages: list[dict[str, Any]]) -> str:
    return "\n".join(
        [
            f"Tick: {state.tick}",
            "Talk transcript:",
            _chat_messages_text(phase_messages, state),
        ]
    )


def _fallback_talk_summary(state: State, phase_messages: list[dict[str, Any]]) -> str:
    lines = []
    for message in phase_messages[-4:]:
        peer = message.get("from") or message.get("to") or message.get("peer") or "?"
        label = _agent_label_from_public_key(state, peer)
        lines.append(f"{label}: {_one_line(str(message.get('message', '')), 120)}")
    return " | ".join(lines)


def _valid_talk_recipients(state: State) -> set[str]:
    recipients = _visible_talk_recipients(state)
    for action in state.get_valid_actions():
        if action.get("action") != "talk_to":
            continue
        targets = action.get("targets", [])
        if not isinstance(targets, list):
            targets = []
        for target in targets:
            if isinstance(target, str):
                recipients.add(target)
            elif isinstance(target, dict) and isinstance(target.get("public_key"), str):
                recipients.add(target["public_key"])
        target = action.get("target")
        if isinstance(target, str):
            recipients.add(target)
        elif isinstance(target, dict) and isinstance(target.get("public_key"), str):
            recipients.add(target["public_key"])
    return recipients


def _visible_talk_recipients(state: State) -> set[str]:
    recipients = set()
    self_agent = _agent_state(state)
    self_id = self_agent.get("id")
    self_public_key = self_agent.get("public_key")
    for tile in state.sim_state.get("visible_map", []):
        if not isinstance(tile, dict):
            continue
        for occupant in tile.get("occupants", []):
            if not isinstance(occupant, dict) or not occupant.get("alive", True):
                continue
            public_key = occupant.get("public_key")
            if not isinstance(public_key, str) or not public_key:
                continue
            if occupant.get("id") == self_id or public_key == self_public_key:
                continue
            recipients.add(public_key)
    return recipients


def _talk_recipients_text(state: State) -> str:
    recipients = sorted(_valid_talk_recipients(state))
    if not recipients:
        return "none"
    return ", ".join(_agent_label_from_public_key(state, recipient) for recipient in recipients)


def _peer_list_text(state: State, recipients: set[str]) -> str:
    if not recipients:
        return "none"
    return ", ".join(
        _agent_label_from_public_key(state, recipient)
        for recipient in sorted(recipients)
    )


def _chat_messages_text(messages: list[dict[str, Any]], state: State | None = None) -> str:
    if not messages:
        return "none"
    lines = []
    for message in messages[-config.CHAT_CONTEXT_LIMIT:]:
        direction = message.get("direction")
        peer = message.get("from") or message.get("to") or message.get("peer") or "?"
        peer_text = _chat_peer_label(state, peer) if state is not None else str(peer)
        lines.append(f"{direction or 'incoming'} {peer_text}: {_one_line(str(message.get('message', '')), 180)}")
    return "\n".join(lines)


def _filter_talk_messages(
    messages: list[dict[str, Any]],
    state: State,
    talk_budget_limit: float,
    *,
    allowed_recipients: set[str] | None = None,
    max_messages: int | None = None,
) -> list[dict[str, str]]:
    talk_budget = _talk_to_budget(state) or config.CHAT_ACTION_BUDGET
    max_by_budget = int(talk_budget_limit // max(talk_budget, 0.0001))
    message_limit = max(0, min(config.MAX_TALK_MESSAGES_PER_TICK, max_by_budget))
    if max_messages is not None:
        message_limit = min(message_limit, max(0, max_messages))
    if message_limit <= 0:
        return []

    valid_recipients = set(allowed_recipients) if allowed_recipients is not None else _valid_talk_recipients(state)
    selected = []
    seen_recipients = set()
    for raw_message in messages[: config.MAX_TALK_MESSAGES_PER_TICK]:
        recipient = _message_recipient_for_transport(state, raw_message.get("recipient"), valid_recipients)
        content = raw_message.get("content")
        if recipient is None:
            logger.warning("skipping talk message without valid talk recipient raw_message=%s", raw_message)
            continue
        if recipient in seen_recipients:
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        selected.append(
            {
                "recipient": recipient,
                "recipient_label": _agent_label_from_public_key(state, recipient),
                "content": content.strip()[: config.MAX_AGENT_MESSAGE_CHARS],
            }
        )
        seen_recipients.add(recipient)
        if len(selected) >= message_limit:
            break
    return selected


def _send_llm_response(
    llm_response: dict[str, Any],
    state: State,
    self_public_key: str,
    *,
    action_budget: float | None = None,
    allow_talk: bool = True,
    prefix_actions: list[dict[str, Any]] | None = None,
    talk_budget: float | None = None,
    talk_budget_spent: float = 0.0,
) -> dict[str, Any]:
    prefix_actions = list(prefix_actions or [])
    actions = _filter_actions(
        llm_response.get("actions", []),
        state.get_valid_actions(),
        _agent_action_budget(state) if action_budget is None else action_budget,
        state,
        allow_talk=allow_talk,
    )
    if not actions:
        wait_action = _default_wait_action(state.get_valid_actions())
        if wait_action is not None:
            actions = [wait_action]
            logger.info("using fallback wait action tick=%s", state.tick)

    actions = _talk_actions_first(prefix_actions + actions)
    tick = state.tick
    logger.info("accepted actions tick=%s actions=%s", tick, actions)
    available_action_budget = _agent_action_budget(state) if action_budget is None else action_budget
    action_budget_used = _action_budget_used(actions, state, include_talk=allow_talk)
    budget_text = f"action budget {action_budget_used:.2f}/{available_action_budget:.2f}"
    if talk_budget is not None:
        budget_text = f"{budget_text} | talk budget {talk_budget_spent:.2f}/{talk_budget:.2f}"
    demo_log(logger, "Decision: %s | %s", _demo_actions(actions, state), budget_text)

    talk_recipients = _talk_recipients(actions)
    accepted_messages = (
        _filter_agent_messages(llm_response.get("messages", []), talk_recipients, state)
        if allow_talk
        else []
    )
    talk_actions = [action for action in actions if action.get("action") == "talk_to"]
    non_talk_actions = [action for action in actions if action.get("action") != "talk_to"]

    for message in accepted_messages:
        demo_log(
            logger,
            "You -> %s: %s",
            _agent_label_from_public_key(state, message["recipient"]),
            _one_line(message["content"], 240),
        )
        _send_agent_message(message["recipient"], message["content"], tick, self_public_key)
    _send_agent_actions(talk_actions + non_talk_actions, tick, self_public_key)

    return {"actions": actions, "messages": accepted_messages}


def _talk_actions_first(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        *[action for action in actions if action.get("action") == "talk_to"],
        *[action for action in actions if action.get("action") != "talk_to"],
    ]


def _filter_actions(
    actions: list[dict[str, Any]],
    valid_actions: list[dict[str, Any]],
    action_budget: float,
    state: State,
    *,
    allow_talk: bool = True,
) -> list[dict[str, Any]]:
    valid_action_specs = _valid_action_specs(valid_actions)
    remaining_budget = max(0.0, action_budget)

    selected_actions = []
    for raw_action in actions[: config.MAX_ACTIONS_PER_TICK]:
        action = _wire_action(raw_action)
        if action is None:
            logger.warning("skipping invalid LLM action raw_action=%s", raw_action)
            continue
        action = _action_for_transport(action, state)
        if action is None:
            logger.warning("skipping LLM action with unresolved agent name raw_action=%s", raw_action)
            continue

        if not allow_talk and action["action"] == "talk_to":
            logger.info("skipping action-phase talk_to; planning chat phase handles talk")
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


def _action_budget_used(actions: list[dict[str, Any]], state: State, *, include_talk: bool) -> float:
    valid_action_specs = _valid_action_specs(state.get_valid_actions())
    used = 0.0
    for action in actions:
        action_name = action.get("action")
        if not include_talk and action_name == "talk_to":
            continue
        spec = valid_action_specs.get(action_name)
        if spec is not None:
            used += float(spec.get("budget", 0.0))
    return used


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
    state: State,
) -> list[dict[str, str]]:
    selected_messages = []
    for raw_message in messages[: config.MAX_AGENT_MESSAGES_PER_TICK]:
        recipient = _message_recipient_for_transport(state, raw_message.get("recipient"), talk_recipients)
        content = raw_message.get("content")
        if recipient is None:
            logger.warning("skipping agent message without matching talk_to action raw_message=%s", raw_message)
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        selected_messages.append(
            {
                "recipient": recipient,
                "recipient_label": _agent_label_from_public_key(state, recipient),
                "content": content.strip()[: config.MAX_AGENT_MESSAGE_CHARS],
            }
        )
    return selected_messages


def _message_recipient_for_transport(
    state: State,
    raw_recipient: Any,
    allowed_public_keys: set[str],
) -> str | None:
    if not isinstance(raw_recipient, str):
        return None

    if raw_recipient in allowed_public_keys:
        logger.warning("rejecting public-key recipient from LLM; use listed agent name")
        return None

    public_key = _agent_public_key_from_label(state, raw_recipient)
    if public_key is None or public_key not in allowed_public_keys:
        return None
    return public_key


def _action_for_transport(action: dict[str, Any], state: State) -> dict[str, Any] | None:
    action_name = action.get("action")
    if action_name not in LABEL_TARGET_ACTIONS:
        return action

    target = action.get("target")
    if not isinstance(target, str):
        return None

    if action_name == "talk_to":
        public_key = _agent_public_key_from_label(state, target)
        if public_key is None or public_key not in _valid_talk_recipients(state):
            return None
        action["target"] = public_key
        return action

    target_payload = _agent_target_from_label(state, target)
    if target_payload is None or target_payload["public_key"] not in _visible_talk_recipients(state):
        return None
    action["target"] = target_payload
    return action


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


def _send_agent_actions(actions: list[dict[str, Any]], tick: int | None, self_public_key: str) -> None:
    content = {
        "sender_public_key": self_public_key,
        "actions": actions,
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
    logger.info("sent AGENT_ACTION batch tick=%s actions=%s server=%s", tick, actions, config.SERVER_PUBLIC_KEY)


def _send_agent_message(recipient: str, content: str, tick: int, self_public_key: str) -> None:
    if _normalize_agent_label(recipient) is not None:
        logger.error("refusing to send AGENT_MSG to unresolved agent name recipient=%s", recipient)
        return

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
    logger.info("sent AGENT_MSG tick=%s recipient_public_key=%s message=%s", tick, recipient, content)


def _send_agent_profile(profile: dict[str, Any], self_public_key: str) -> None:
    content = {
        "sender_public_key": self_public_key,
        "agent_profile": profile,
    }
    message = {
        "protocol_version": config.PROTOCOL_VERSION,
        "message_type": config.MESSAGE_TYPE_AGENT_PROFILE,
        "sender_public_key": self_public_key,
        "content": content,
    }
    axl.send(message, config.SERVER_PUBLIC_KEY)
    logger.info(
        "sent AGENT_PROFILE server=%s agent_name=%s wallet=%s",
        config.SERVER_PUBLIC_KEY,
        profile.get("ens_name"),
        profile.get("wallet_address"),
    )


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
            f"Phase: {state.sim_state.get('phase', 'day')}",
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
            name = _results_agent_name(state, row.get("agent_id"), row)
            lines.append(
                f"#{row.get('rank', '?')} {name} {status} "
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
                f"{_results_agent_name(state, kill.get('killer_id'))} killed "
                f"{_results_agent_name(state, kill.get('victim_id'))}"
            )

    deaths = results.get("deaths", [])
    if isinstance(deaths, list) and deaths:
        lines.append("Deaths:")
        for death in deaths:
            if not isinstance(death, dict):
                continue
            killed_by = death.get("killed_by")
            killer = "" if killed_by is None else f" by {_results_agent_name(state, killed_by)}"
            lines.append(
                f"tick {death.get('tick', '?')}: "
                f"{_results_agent_name(state, death.get('agent_id'))} died{killer} ({death.get('cause', '?')})"
            )

    action_counts = results.get("action_counts", {})
    if isinstance(action_counts, dict) and action_counts:
        lines.append("Actions:")
        for agent_key in sorted(action_counts, key=lambda value: int(value) if str(value).isdigit() else str(value)):
            counts = action_counts.get(agent_key)
            if not isinstance(counts, dict):
                continue
            count_text = ", ".join(f"{name}={count}" for name, count in sorted(counts.items())) or "none"
            lines.append(f"{_results_agent_name(state, agent_key)}: {count_text}")

    return "\n".join(lines)


def _results_agent_name(state: State, agent_id: Any, row: dict[str, Any] | None = None) -> str:
    if isinstance(row, dict):
        name = row.get("name") or row.get("ens_name")
        if isinstance(name, str) and name:
            return name

    try:
        normalized_id: Any = int(agent_id)
    except (TypeError, ValueError):
        normalized_id = agent_id

    for candidate in _known_agents(state):
        if candidate.get("id") == normalized_id or str(candidate.get("id")) == str(agent_id):
            return _agent_label(candidate)
    return f"A{agent_id}"


def _llm_state_description(state: State) -> str:
    prompt_state = _sanitize_llm_value(state, deepcopy(state.sim_state))
    prompt_state["valid_actions"] = _llm_valid_actions(state)
    prompt_state["incoming_agent_messages"] = _llm_chat_messages(state, state.agent_messages)
    prompt_state["recent_agent_messages"] = _llm_chat_messages(state, state.recent_agent_messages)
    prompt_state["talk_phase"] = _sanitize_llm_value(state, deepcopy(state.talk_phase))
    prompt_state["state_history_length"] = len(state.state_history)
    return json.dumps(prompt_state, indent=2, ensure_ascii=False)


def _record_action_llm_artifact(state: State, request_payload: dict[str, Any], response: dict[str, Any]) -> None:
    if not is_demo_logging():
        return

    sim_id = str(state.sim_state.get("sim_id") or "unmatched")
    tick = state.tick
    safe_sim_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in sim_id)[:96] or "unmatched"
    output_dir = Path(config.CLIENT_LLM_ACTION_LOG_DIR).expanduser() / safe_sim_id
    artifact = {
        "sim_id": sim_id,
        "tick": tick,
        "created_at": time.time(),
        "model": config.OLLAMA_MODEL,
        "prompt": _payload_prompt_text(request_payload),
        "request": request_payload,
        "response": response,
    }

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"tick_{tick:04d}_action.json"
        path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("stored action LLM artifact tick=%s path=%s", tick, path)
    except OSError as exc:
        logger.warning("failed to store action LLM artifact tick=%s: %s", tick, exc)


def _payload_prompt_text(payload: dict[str, Any]) -> str:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return ""

    parts = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "message").upper()
        content = str(message.get("content") or "")
        parts.append(f"{role}:\n{content}")
    return "\n\n".join(parts)


def _llm_valid_actions(state: State) -> list[dict[str, Any]]:
    actions = []
    for action in state.get_valid_actions():
        prompt_action = _sanitize_llm_value(state, deepcopy(action))
        action_name = prompt_action.get("action")
        if action_name in LABEL_TARGET_ACTIONS:
            prompt_action["target_format"] = "agent_name"
            required_fields = prompt_action.get("required_fields")
            if isinstance(required_fields, dict):
                required_fields["target"] = "Agent name string from targets, for example an ENS name."

            labels = _llm_action_target_labels(state, str(action_name))
            if labels:
                prompt_action["targets"] = labels
        actions.append(prompt_action)
    return actions


def _llm_action_target_labels(state: State, action_name: str) -> list[str]:
    if action_name == "talk_to":
        public_keys = _valid_talk_recipients(state)
    else:
        public_keys = _visible_talk_recipients(state)

    labels = [
        _agent_label_from_public_key(state, public_key)
        for public_key in sorted(public_keys)
    ]
    return [label for label in labels if label != "A?"]


def _llm_chat_messages(state: State, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _sanitize_llm_value(state, deepcopy(message))
        for message in messages
    ]


def _sanitize_llm_value(state: State, value: Any) -> Any:
    public_key_labels = _public_key_labels(state)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        label = _llm_dict_agent_label(state, value)
        for key, nested_value in value.items():
            if key in {"public_key", "sender_public_key", "agent_public_key"}:
                if label != "A?":
                    result.setdefault("label", label)
                continue
            result[key] = _sanitize_llm_value(state, nested_value)

        if label != "A?":
            result.setdefault("label", label)
        return result

    if isinstance(value, list):
        return [_sanitize_llm_value(state, item) for item in value]

    if isinstance(value, str) and value in public_key_labels:
        return public_key_labels[value]

    return value


def _llm_dict_agent_label(state: State, value: dict[str, Any]) -> str:
    agent_id = value.get("id")
    if not isinstance(agent_id, int):
        agent_id = value.get("agent_id")
    public_key = value.get("public_key") or value.get("sender_public_key") or value.get("agent_public_key")
    if isinstance(public_key, str):
        return _agent_label_from_public_key(state, public_key)
    if isinstance(agent_id, int):
        return _agent_label(value)

    return "A?"


def _demo_state_block(state: State) -> str:
    agent = _agent_state(state)
    status = "" if agent.get("alive", True) else f" dead:{agent.get('death_cause') or '?'}"
    lines = [
        f"Tick {state.tick} | {state.sim_state.get('phase', 'day')} | temp {_number(state.sim_state.get('temp'))}C",
        (
            f"You are {_agent_label(agent)} at {_position_text(agent.get('position'))} | "
            f"hp={_number(agent.get('health'))} "
            f"hunger={_number(agent.get('hunger'))} "
            f"thirst={_number(agent.get('thirst'))} "
            f"warmth={_number(agent.get('warmth'))} "
            f"carry={_number(agent.get('inventory_weight'))}/{_number(agent.get('carry_capacity'))}{status}"
        ),
        f"Inventory: {_inventory_text(agent.get('inventory'))}",
        f"Current tile resources: {_current_tile_resources_text(state)}",
        "Visible map:",
        _render_visible_map(state),
    ]

    if state.agent_messages:
        lines.append("Incoming chat:")
        for message in state.agent_messages:
            lines.append(
                f"{_chat_peer_label(state, message.get('from'))} -> You: "
                f"{_one_line(str(message.get('message', '')), 240)}"
            )

    recent_messages = [
        message
        for message in state.recent_agent_messages[-config.CHAT_CONTEXT_LIMIT:]
        if message not in state.agent_messages
    ]
    if recent_messages:
        lines.append("Recent chat:")
        for message in recent_messages:
            direction = message.get("direction")
            if direction == "outgoing":
                lines.append(
                    f"You -> {_chat_peer_label(state, message.get('to'))}: "
                    f"{_one_line(str(message.get('message', '')), 180)}"
                )
            else:
                lines.append(
                    f"{_chat_peer_label(state, message.get('from'))} -> You: "
                    f"{_one_line(str(message.get('message', '')), 180)}"
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
    if agent_id is None:
        agent_id = agent.get("agent_id")
    return agent_display_name(
        agent_id=agent_id,
        public_key=agent.get("public_key") or agent.get("sender_public_key") or agent.get("agent_public_key"),
        profile=_agent_profile(agent),
    )


def _agent_label_from_target(state: State, target: Any) -> str:
    if isinstance(target, dict):
        label = target.get("label") or target.get("name") or target.get("ens_name")
        if isinstance(label, str) and label:
            return label
        if "id" in target:
            for candidate in _known_agents(state):
                if candidate.get("id") == target["id"]:
                    return _agent_label(candidate)
            return f"A{target['id']}"
        if isinstance(target.get("public_key"), str):
            return _agent_label_from_public_key(state, target["public_key"])
    if isinstance(target, int):
        return _results_agent_name(state, target)
    if isinstance(target, str):
        label = _normalize_agent_label(target)
        if label is not None:
            return _results_agent_name(state, _agent_id_from_label(label))
        public_key = _agent_public_key_from_label(state, target)
        if public_key is not None:
            return _agent_label_from_public_key(state, public_key)
        return _agent_label_from_public_key(state, target)
    return "A?"


def _normalize_agent_label(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) < 2 or text[0].upper() != "A" or not text[1:].isdigit():
        return None
    return f"A{int(text[1:])}"


def _agent_public_key_from_label(state: State, label: str) -> str | None:
    if not isinstance(label, str):
        return None

    text = label.strip()
    agent_id = _agent_id_from_label(text)

    for candidate in _known_agents(state):
        public_key = candidate.get("public_key")
        if not isinstance(public_key, str) or not public_key:
            continue
        if agent_id is not None and candidate.get("id") == agent_id:
            return public_key
        if _agent_name_matches(candidate, text):
            return public_key
    return None


def _agent_target_from_label(state: State, label: str) -> dict[str, Any] | None:
    public_key = _agent_public_key_from_label(state, label)
    if public_key is None:
        return None
    for candidate in _known_agents(state):
        if candidate.get("public_key") == public_key:
            return {
                "id": candidate.get("id"),
                "name": _agent_label(candidate),
                "ens_name": candidate.get("ens_name"),
                "public_key": public_key,
            }
    agent_id = _agent_id_from_label(label)
    return {"id": agent_id, "public_key": public_key}


def _agent_id_from_label(label: str) -> int | None:
    normalized = _normalize_agent_label(label)
    if normalized is None:
        return None
    return int(normalized[1:])


def _public_key_labels(state: State) -> dict[str, str]:
    labels: dict[str, str] = {}
    for candidate in _known_agents(state):
        public_key = candidate.get("public_key")
        if isinstance(public_key, str) and public_key:
            labels[public_key] = _agent_label(candidate)
    return labels


def _agent_label_from_public_key(state: State, public_key: Any) -> str:
    if not isinstance(public_key, str) or not public_key:
        return "A?"

    for candidate in _known_agents(state):
        if candidate.get("public_key") == public_key:
            return _agent_label(candidate)
    return "A?"


def _agent_id_from_public_key(state: State, public_key: Any) -> int | None:
    if not isinstance(public_key, str) or not public_key:
        return None

    for candidate in _known_agents(state):
        if candidate.get("public_key") == public_key and isinstance(candidate.get("id"), int):
            return candidate["id"]
    return None


def _chat_peer_label(state: State | None, public_key: Any) -> str:
    label = _normalize_agent_label(public_key)
    if label is not None:
        return label
    if state is not None:
        resolved_label = _agent_label_from_public_key(state, public_key)
        if resolved_label != "A?":
            return resolved_label
    if isinstance(public_key, str) and public_key:
        if "." in public_key and len(public_key) <= 255:
            return public_key
        return public_key[:8]
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


def _known_agents(state: State) -> list[dict[str, Any]]:
    agents: list[dict[str, Any]] = []
    self_agent = _agent_state(state)
    if self_agent:
        agents.append(self_agent)

    for row in state.sim_state.get("scoreboard", []):
        if isinstance(row, dict):
            agents.append(
                {
                    "id": row.get("agent_id"),
                    "name": row.get("name") or row.get("ens_name"),
                    "ens_name": row.get("ens_name"),
                    "public_key": row.get("public_key"),
                    "profile": row.get("profile"),
                }
            )

    for tile in state.sim_state.get("visible_map", []):
        if not isinstance(tile, dict):
            continue
        for occupant in tile.get("occupants", []):
            if isinstance(occupant, dict):
                agents.append(occupant)

    deduped: dict[str, dict[str, Any]] = {}
    for agent in agents:
        public_key = agent.get("public_key")
        key = public_key if isinstance(public_key, str) and public_key else str(agent.get("id"))
        deduped[key] = {**deduped.get(key, {}), **agent}
    return list(deduped.values())


def _agent_profile(agent: dict[str, Any]) -> dict[str, Any]:
    profile = agent.get("profile")
    if isinstance(profile, dict):
        return profile
    return agent


def _agent_name_matches(agent: dict[str, Any], raw_label: str) -> bool:
    text = raw_label.strip().rstrip(".").lower()
    if not text:
        return False

    for key in ("label", "name", "ens_name"):
        value = agent.get(key)
        if isinstance(value, str) and value.strip().rstrip(".").lower() == text:
            return True

    return profile_matches_name(_agent_profile(agent), text)


def _inventory_text(inventory: Any) -> str:
    if not isinstance(inventory, dict) or not inventory:
        return "empty"
    return ", ".join(f"{item}={amount}" for item, amount in inventory.items())


def _current_tile_resources_text(state: State) -> str:
    position = _agent_state(state).get("position")
    if not isinstance(position, dict):
        return "unknown"

    for tile in state.sim_state.get("visible_map", []):
        if not isinstance(tile, dict):
            continue
        if tile.get("x") == position.get("x") and tile.get("y") == position.get("y"):
            resources = _inventory_text(tile.get("resources"))
            return "none" if resources == "empty" else resources
    return "unknown"


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
