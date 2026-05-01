from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any
from urllib import error, request

from . import config
from common.logging_config import demo_log


logger = logging.getLogger(__name__)


ACTION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "target": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "number"},
                            {"type": "integer"},
                            {"type": "object"},
                            {"type": "array"},
                            {"type": "null"},
                        ]
                    },
                    "consumable": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "number"},
                            {"type": "integer"},
                            {"type": "object"},
                            {"type": "array"},
                            {"type": "null"},
                        ]
                    },
                    "item": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "number"},
                            {"type": "integer"},
                            {"type": "object"},
                            {"type": "array"},
                            {"type": "null"},
                        ]
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
        "messages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "recipient": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["recipient", "content"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["actions", "messages"],
    "additionalProperties": False,
}


PLAN_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "messages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "recipient": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["recipient", "content"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["messages"],
    "additionalProperties": False,
}


SUMMARY_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
    },
    "required": ["summary"],
    "additionalProperties": False,
}


SYSTEM_PROMPT = """
You are choosing the action phase for a survival simulation agent after a talk phase.
Return only JSON that matches the provided schema.
Choose actions from the valid_actions list in the prompt.
Fill required fields using agent, visible_map, inventory, and talk_phase.summary.
Use coordinates from visible_map, resource names from inventory/resources, and agent labels like A0 or A1 for visible agents.
For talk_to, attack, and trade targets, return only the listed agent label string. Do not return public keys.
The sum of selected action budgets must be <= agent.action_budget.
Do not pick up or request resources if carrying them would exceed carry_capacity.
Do not say you have or can trade an item unless it is present in agent.inventory; visible_map resources are on the ground.
Move can use any valid move target, including diagonal targets.
Treat hunger >70, thirst >50, and warmth <30 as urgent survival problems.
For trade, use consumable as the resource you offer and item as the resource you request; trade only resolves when both agents submit matching trade actions.
Talk belongs in the talk phase; in this action phase, prefer movement, survival, resource, trade, rest, or combat actions.
Do not include explanations, markdown, or keys outside the schema.
"""


PLAN_SYSTEM_PROMPT = """
You are in the talk phase before actions in a survival simulation.
Return only JSON that matches the provided schema.
Choose at most the allowed talk messages.
Use only listed talk recipient labels like A0 or A1. Do not return public keys.
Keep messages short, practical, and tied to the current tick.
Do not claim you carry resources unless they are in Inventory.
Do not choose movement, eating, gathering, combat, or trade actions here; this phase is only for talking to agents.
You may open, reply, coordinate, warn, deceive, threaten, or stay silent.
Return an empty messages array when the peer only acknowledged, agreed, gave permission, or committed to an action and there is no new question.
Do not repeat commitments already made in the transcript.
Return an empty messages array when you do not want to speak right now.
"""


SUMMARY_SYSTEM_PROMPT = """
Summarize the talk phase for the action decision.
Return only JSON that matches the provided schema.
Write at most two short lines.
Keep only agreements, threats, offers, requests, warnings, and useful intentions.
Do not add advice, plans, or facts that were not in the conversation.
"""


DIRECT_CHAT_SYSTEM_PROMPT = """
You are replying to another agent in a survival simulation.
Use the current state context and the incoming message.
Write only the chat message text to send back.
Do not write JSON, markdown, labels, quotes, or explanations.
Do not claim you carry resources unless they are in your inventory.
Keep it short, practical, and in character.
"""


def get_plan_response(prompt: str) -> dict[str, Any]:
    try:
        payload = _create_plan_payload(prompt)
        base_url = config.OLLAMA_BASE_URL.rstrip("/")
        estimated_prompt_tokens = _estimate_tokens(prompt)
        estimated_total_tokens = estimated_prompt_tokens + config.OLLAMA_PLAN_RESPONSE_TOKENS
        demo_log(
            logger,
            "LLM talk call: model=%s prompt_chars=%s est_tokens=%s ctx=%s response_tokens=%s fits=%s",
            config.OLLAMA_MODEL,
            len(prompt),
            estimated_prompt_tokens,
            config.OLLAMA_CONTEXT_LENGTH,
            config.OLLAMA_PLAN_RESPONSE_TOKENS,
            estimated_total_tokens <= config.OLLAMA_CONTEXT_LENGTH,
        )
        logger.info(
            "ollama plan request model=%s base_url=%s think=%s prompt_chars=%s estimated_prompt_tokens=%s response_token_limit=%s context_length=%s estimated_total_tokens=%s estimated_fits_context=%s",
            config.OLLAMA_MODEL,
            base_url,
            config.OLLAMA_PLAN_THINK,
            len(prompt),
            estimated_prompt_tokens,
            config.OLLAMA_PLAN_RESPONSE_TOKENS,
            config.OLLAMA_CONTEXT_LENGTH,
            estimated_total_tokens,
            estimated_total_tokens <= config.OLLAMA_CONTEXT_LENGTH,
        )

        start_time = time.monotonic()
        response = _post_json(
            f"{base_url}/api/chat",
            payload,
            stream_label="Talk",
            display_content=config.OLLAMA_STREAM_JSON_LOG,
        )
        elapsed = time.monotonic() - start_time
        content = _extract_chat_content(response)
        reasoning = _extract_chat_reasoning(response)
        parsed = _parse_json_content(content)
        normalized = normalize_plan_response(parsed)
        normalized["reasoning"] = reasoning
        usage = _usage_summary(response)
        demo_log(
            logger,
            "LLM talk done: elapsed=%.2fs messages=%s response_tokens=%s tps=%s done=%s",
            elapsed,
            len(normalized["messages"]),
            usage.get("response_tokens"),
            usage.get("tokens_per_second"),
            usage.get("done_reason"),
        )
        logger.info(
            "ollama talk response elapsed=%.2fs model=%s messages=%s reasoning_chars=%s usage=%s",
            elapsed,
            response.get("model"),
            normalized["messages"],
            len(reasoning),
            usage,
        )
        return normalized
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError, error.URLError) as exc:
        logger.warning("ollama talk request failed, skipping talk phase chat: %s", exc)
        return {"messages": [], "reasoning": ""}


def get_summary_response(prompt: str) -> dict[str, str]:
    try:
        payload = _create_summary_payload(prompt)
        base_url = config.OLLAMA_BASE_URL.rstrip("/")
        estimated_prompt_tokens = _estimate_tokens(prompt)
        estimated_total_tokens = estimated_prompt_tokens + config.OLLAMA_SUMMARY_RESPONSE_TOKENS
        demo_log(
            logger,
            "LLM summary call: model=%s prompt_chars=%s est_tokens=%s ctx=%s response_tokens=%s fits=%s",
            config.OLLAMA_MODEL,
            len(prompt),
            estimated_prompt_tokens,
            config.OLLAMA_CONTEXT_LENGTH,
            config.OLLAMA_SUMMARY_RESPONSE_TOKENS,
            estimated_total_tokens <= config.OLLAMA_CONTEXT_LENGTH,
        )
        logger.info(
            "ollama summary request model=%s base_url=%s think=%s prompt_chars=%s estimated_prompt_tokens=%s response_token_limit=%s context_length=%s estimated_total_tokens=%s estimated_fits_context=%s",
            config.OLLAMA_MODEL,
            base_url,
            config.OLLAMA_SUMMARY_THINK,
            len(prompt),
            estimated_prompt_tokens,
            config.OLLAMA_SUMMARY_RESPONSE_TOKENS,
            config.OLLAMA_CONTEXT_LENGTH,
            estimated_total_tokens,
            estimated_total_tokens <= config.OLLAMA_CONTEXT_LENGTH,
        )
        start_time = time.monotonic()
        response = _post_json(
            f"{base_url}/api/chat",
            payload,
            stream_label="Summary",
            display_content=config.OLLAMA_STREAM_JSON_LOG,
        )
        elapsed = time.monotonic() - start_time
        content = _extract_chat_content(response)
        parsed = _parse_json_content(content)
        normalized = normalize_summary_response(parsed)
        usage = _usage_summary(response)
        demo_log(
            logger,
            "LLM summary done: elapsed=%.2fs summary_chars=%s response_tokens=%s tps=%s done=%s",
            elapsed,
            len(normalized["summary"]),
            usage.get("response_tokens"),
            usage.get("tokens_per_second"),
            usage.get("done_reason"),
        )
        logger.info(
            "ollama summary response elapsed=%.2fs model=%s summary_chars=%s usage=%s",
            elapsed,
            response.get("model"),
            len(normalized["summary"]),
            usage,
        )
        return normalized
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError, error.URLError) as exc:
        logger.warning("ollama summary request failed, using compact transcript summary: %s", exc)
        return {"summary": ""}


def get_llm_response(prompt: str) -> dict[str, Any]:
    try:
        payload = _create_chat_payload(prompt)
        base_url = config.OLLAMA_BASE_URL.rstrip("/")
        estimated_prompt_tokens = _estimate_tokens(prompt)
        estimated_total_tokens = estimated_prompt_tokens + config.OLLAMA_RESPONSE_TOKENS
        demo_log(
            logger,
            "LLM action call: model=%s prompt_chars=%s est_tokens=%s ctx=%s response_tokens=%s fits=%s",
            config.OLLAMA_MODEL,
            len(prompt),
            estimated_prompt_tokens,
            config.OLLAMA_CONTEXT_LENGTH,
            config.OLLAMA_RESPONSE_TOKENS,
            estimated_total_tokens <= config.OLLAMA_CONTEXT_LENGTH,
        )
        logger.info(
            "ollama request model=%s base_url=%s think=%s options=%s prompt_chars=%s estimated_prompt_tokens=%s response_token_limit=%s context_length=%s estimated_total_tokens=%s estimated_fits_context=%s",
            config.OLLAMA_MODEL,
            base_url,
            config.OLLAMA_THINK,
            payload["options"],
            len(prompt),
            estimated_prompt_tokens,
            config.OLLAMA_RESPONSE_TOKENS,
            config.OLLAMA_CONTEXT_LENGTH,
            estimated_total_tokens,
            estimated_total_tokens <= config.OLLAMA_CONTEXT_LENGTH,
        )
        logger.debug("ollama prompt\n%s", prompt)

        start_time = time.monotonic()
        response = _post_json(
            f"{base_url}/api/chat",
            payload,
            stream_label="LLM",
            display_content=config.OLLAMA_STREAM_JSON_LOG,
        )
        elapsed = time.monotonic() - start_time
        content = _extract_chat_content(response)
        reasoning = _extract_chat_reasoning(response)
        parsed = _parse_json_content(content)
        normalized = normalize_llm_response(parsed)
        normalized["reasoning"] = reasoning
        usage = _usage_summary(response)
        demo_log(
            logger,
            "LLM action done: elapsed=%.2fs actions=%s messages=%s response_tokens=%s tps=%s done=%s",
            elapsed,
            len(normalized["actions"]),
            len(normalized["messages"]),
            usage.get("response_tokens"),
            usage.get("tokens_per_second"),
            usage.get("done_reason"),
        )
        logger.info(
            "ollama response elapsed=%.2fs model=%s actions=%s messages=%s reasoning_chars=%s usage=%s",
            elapsed,
            response.get("model"),
            normalized["actions"],
            normalized["messages"],
            len(reasoning),
            usage,
        )
        if reasoning:
            logger.info("ollama reasoning\n%s", reasoning)
        else:
            logger.info("ollama reasoning not returned; set OLLAMA_THINK=true/high/medium/low if the model supports it")
        logger.debug("ollama raw response=%s", response)
        return normalized
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError, error.URLError) as exc:
        logger.warning("ollama request failed, falling back to wait: %s", exc)
        return {"actions": [{"action": "wait"}], "messages": [], "reasoning": ""}


def get_chat_response(prompt: str) -> dict[str, str]:
    try:
        payload = _create_direct_chat_payload(prompt)
        base_url = config.OLLAMA_BASE_URL.rstrip("/")
        estimated_prompt_tokens = _estimate_tokens(prompt)
        estimated_total_tokens = estimated_prompt_tokens + config.OLLAMA_CHAT_RESPONSE_TOKENS
        demo_log(
            logger,
            "LLM direct-chat call: model=%s prompt_chars=%s est_tokens=%s ctx=%s response_tokens=%s fits=%s",
            config.OLLAMA_MODEL,
            len(prompt),
            estimated_prompt_tokens,
            config.OLLAMA_CONTEXT_LENGTH,
            config.OLLAMA_CHAT_RESPONSE_TOKENS,
            estimated_total_tokens <= config.OLLAMA_CONTEXT_LENGTH,
        )
        logger.info(
            "ollama chat request model=%s base_url=%s think=%s prompt_chars=%s estimated_prompt_tokens=%s response_token_limit=%s context_length=%s estimated_total_tokens=%s estimated_fits_context=%s",
            config.OLLAMA_MODEL,
            base_url,
            config.OLLAMA_CHAT_THINK,
            len(prompt),
            estimated_prompt_tokens,
            config.OLLAMA_CHAT_RESPONSE_TOKENS,
            config.OLLAMA_CONTEXT_LENGTH,
            estimated_total_tokens,
            estimated_total_tokens <= config.OLLAMA_CONTEXT_LENGTH,
        )
        logger.debug("ollama chat prompt\n%s", prompt)

        start_time = time.monotonic()
        response = _post_json(
            f"{base_url}/api/chat",
            payload,
            stream_label="Chat",
            display_content=True,
        )
        elapsed = time.monotonic() - start_time
        content = _normalize_chat_content(_extract_chat_content(response))
        reasoning = _extract_chat_reasoning(response)
        usage = _usage_summary(response)
        demo_log(
            logger,
            "LLM direct-chat done: elapsed=%.2fs reply_chars=%s response_tokens=%s tps=%s done=%s",
            elapsed,
            len(content),
            usage.get("response_tokens"),
            usage.get("tokens_per_second"),
            usage.get("done_reason"),
        )
        logger.info(
            "ollama chat response elapsed=%.2fs model=%s reply_chars=%s reasoning_chars=%s usage=%s",
            elapsed,
            response.get("model"),
            len(content),
            len(reasoning),
            usage,
        )
        if reasoning:
            logger.info("ollama chat reasoning\n%s", reasoning)
        logger.debug("ollama chat raw response=%s", response)
        return {"content": content[: config.MAX_AGENT_MESSAGE_CHARS], "reasoning": reasoning}
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError, error.URLError) as exc:
        logger.warning("ollama chat request failed, not replying: %s", exc)
        return {"content": "", "reasoning": ""}


def normalize_llm_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("LLM response must be an object")

    actions = []
    for raw_action in payload.get("actions", []):
        action = _normalize_action(raw_action)
        if action is not None:
            actions.append(action)

    messages = []
    for raw_message in payload.get("messages", []):
        message = _normalize_message(raw_message)
        if message is not None:
            messages.append(message)

    return {"actions": actions, "messages": messages}


def normalize_plan_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Plan response must be an object")

    messages = []
    for raw_message in payload.get("messages", []):
        message = _normalize_message(raw_message)
        if message is not None:
            messages.append(message)

    return {"messages": messages}


def normalize_summary_response(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("Summary response must be an object")
    summary = payload.get("summary", "")
    if not isinstance(summary, str):
        summary = ""
    return {"summary": " ".join(summary.split())[:500]}


def _create_plan_payload(prompt: str) -> dict[str, Any]:
    options: dict[str, Any] = {
        "num_ctx": config.OLLAMA_CONTEXT_LENGTH,
        "num_predict": config.OLLAMA_PLAN_RESPONSE_TOKENS,
        "temperature": config.OLLAMA_TEMPERATURE,
        "top_p": config.OLLAMA_TOP_P,
        "top_k": config.OLLAMA_TOP_K,
        "repeat_penalty": config.OLLAMA_REPEAT_PENALTY,
    }

    if config.OLLAMA_SEED:
        options["seed"] = int(config.OLLAMA_SEED)

    schema = json.dumps(PLAN_RESPONSE_SCHEMA, indent=2)
    return {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": PLAN_SYSTEM_PROMPT.strip()},
            {
                "role": "user",
                "content": f"{prompt}\n\nReturn JSON matching this schema:\n{schema}",
            },
        ],
        "stream": config.OLLAMA_STREAM,
        "format": PLAN_RESPONSE_SCHEMA,
        "think": config.OLLAMA_PLAN_THINK,
        "keep_alive": config.OLLAMA_KEEP_ALIVE,
        "options": options,
    }


def _create_summary_payload(prompt: str) -> dict[str, Any]:
    options: dict[str, Any] = {
        "num_ctx": config.OLLAMA_CONTEXT_LENGTH,
        "num_predict": config.OLLAMA_SUMMARY_RESPONSE_TOKENS,
        "temperature": config.OLLAMA_TEMPERATURE,
        "top_p": config.OLLAMA_TOP_P,
        "top_k": config.OLLAMA_TOP_K,
        "repeat_penalty": config.OLLAMA_REPEAT_PENALTY,
    }

    if config.OLLAMA_SEED:
        options["seed"] = int(config.OLLAMA_SEED)

    schema = json.dumps(SUMMARY_RESPONSE_SCHEMA, indent=2)
    return {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT.strip()},
            {
                "role": "user",
                "content": f"{prompt}\n\nReturn JSON matching this schema:\n{schema}",
            },
        ],
        "stream": config.OLLAMA_STREAM,
        "format": SUMMARY_RESPONSE_SCHEMA,
        "think": config.OLLAMA_SUMMARY_THINK,
        "keep_alive": config.OLLAMA_KEEP_ALIVE,
        "options": options,
    }


def _create_chat_payload(prompt: str) -> dict[str, Any]:
    options: dict[str, Any] = {
        "num_ctx": config.OLLAMA_CONTEXT_LENGTH,
        "num_predict": config.OLLAMA_RESPONSE_TOKENS,
        "temperature": config.OLLAMA_TEMPERATURE,
        "top_p": config.OLLAMA_TOP_P,
        "top_k": config.OLLAMA_TOP_K,
        "repeat_penalty": config.OLLAMA_REPEAT_PENALTY,
    }

    if config.OLLAMA_SEED:
        options["seed"] = int(config.OLLAMA_SEED)

    schema = json.dumps(ACTION_RESPONSE_SCHEMA, indent=2)
    return {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT.strip()},
            {
                "role": "user",
                "content": f"{prompt}\n\nReturn JSON matching this schema:\n{schema}",
            },
        ],
        "stream": config.OLLAMA_STREAM,
        "format": ACTION_RESPONSE_SCHEMA,
        "think": config.OLLAMA_THINK,
        "keep_alive": config.OLLAMA_KEEP_ALIVE,
        "options": options,
    }


def _create_direct_chat_payload(prompt: str) -> dict[str, Any]:
    options: dict[str, Any] = {
        "num_ctx": config.OLLAMA_CONTEXT_LENGTH,
        "num_predict": config.OLLAMA_CHAT_RESPONSE_TOKENS,
        "temperature": config.OLLAMA_TEMPERATURE,
        "top_p": config.OLLAMA_TOP_P,
        "top_k": config.OLLAMA_TOP_K,
        "repeat_penalty": config.OLLAMA_REPEAT_PENALTY,
    }

    if config.OLLAMA_SEED:
        options["seed"] = int(config.OLLAMA_SEED)

    return {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": DIRECT_CHAT_SYSTEM_PROMPT.strip()},
            {"role": "user", "content": prompt},
        ],
        "stream": config.OLLAMA_STREAM,
        "think": config.OLLAMA_CHAT_THINK,
        "keep_alive": config.OLLAMA_KEEP_ALIVE,
        "options": options,
    }


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    stream_label: str,
    display_content: bool,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with request.urlopen(req, timeout=config.OLLAMA_TIMEOUT_SECONDS) as resp:
        if payload.get("stream"):
            return _read_streaming_response(resp, stream_label, display_content)
        response_body = resp.read().decode("utf-8")
    return json.loads(response_body)


def _read_streaming_response(resp: Any, stream_label: str, display_content: bool) -> dict[str, Any]:
    result: dict[str, Any] = {}
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    stream_state: dict[str, str | bool] = {}

    for raw_line in resp:
        line = raw_line.decode("utf-8").strip()
        if not line:
            continue

        event = json.loads(line)
        if isinstance(event, dict):
            result.update({key: value for key, value in event.items() if key != "message"})

        message = event.get("message") if isinstance(event, dict) else None
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content:
                content_parts.append(content)
                if display_content:
                    _write_stream_chunk(stream_label, content, stream_state)

            for key in ("thinking", "reasoning"):
                thinking = message.get(key)
                if isinstance(thinking, str) and thinking:
                    thinking_parts.append(thinking)
                    _write_stream_chunk("Thinking", thinking, stream_state)

        for key in ("thinking", "reasoning"):
            thinking = event.get(key) if isinstance(event, dict) else None
            if isinstance(thinking, str) and thinking:
                thinking_parts.append(thinking)
                _write_stream_chunk("Thinking", thinking, stream_state)

    _finish_stream(stream_state)

    result["message"] = {"content": "".join(content_parts)}
    if thinking_parts:
        result["message"]["thinking"] = "".join(thinking_parts)
    return result


def _write_stream_chunk(label: str, chunk: str, stream_state: dict[str, str | bool]) -> None:
    if not config.OLLAMA_STREAM_LOG or not chunk:
        return

    if stream_state.get("label") != label:
        if stream_state.get("open"):
            sys.stdout.write("\n")
        sys.stdout.write(f"{time.strftime('%H:%M:%S')} {label}: ")
        stream_state["label"] = label
        stream_state["open"] = True

    sys.stdout.write(chunk)
    sys.stdout.flush()


def _finish_stream(stream_state: dict[str, str | bool]) -> None:
    if stream_state.get("open"):
        sys.stdout.write("\n")
        sys.stdout.flush()


def _extract_chat_content(response: dict[str, Any]) -> str:
    message = response.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    raise ValueError("Ollama response missing message.content")


def _extract_chat_reasoning(response: dict[str, Any]) -> str:
    message = response.get("message")
    if isinstance(message, dict):
        for key in ("thinking", "reasoning"):
            value = message.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    for key in ("thinking", "reasoning"):
        value = response.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def _usage_summary(response: dict[str, Any]) -> dict[str, Any]:
    prompt_tokens = response.get("prompt_eval_count")
    response_tokens = response.get("eval_count")
    total_tokens = None
    if isinstance(prompt_tokens, int) and isinstance(response_tokens, int):
        total_tokens = prompt_tokens + response_tokens

    eval_duration = response.get("eval_duration")
    tokens_per_second = None
    if isinstance(response_tokens, int) and isinstance(eval_duration, int) and eval_duration > 0:
        tokens_per_second = round(response_tokens / eval_duration * 1_000_000_000, 2)

    return {
        "prompt_tokens": prompt_tokens,
        "response_tokens": response_tokens,
        "total_tokens": total_tokens,
        "context_length": config.OLLAMA_CONTEXT_LENGTH,
        "fits_context": total_tokens <= config.OLLAMA_CONTEXT_LENGTH if total_tokens is not None else None,
        "total_duration_ms": _ns_to_ms(response.get("total_duration")),
        "load_duration_ms": _ns_to_ms(response.get("load_duration")),
        "prompt_eval_duration_ms": _ns_to_ms(response.get("prompt_eval_duration")),
        "eval_duration_ms": _ns_to_ms(eval_duration),
        "tokens_per_second": tokens_per_second,
        "done_reason": response.get("done_reason"),
    }


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _ns_to_ms(value: Any) -> float | None:
    if not isinstance(value, int):
        return None
    return round(value / 1_000_000, 2)


def _parse_json_content(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(content[start : end + 1])


def _normalize_chat_content(content: str) -> str:
    normalized = content.strip()
    if normalized.startswith(("```", "~~~")):
        normalized = normalized.strip("`~").strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
        normalized = normalized[1:-1].strip()
    return " ".join(normalized.split())


def _normalize_action(raw_action: Any) -> dict[str, Any] | None:
    if not isinstance(raw_action, dict):
        return None

    action_name = raw_action.get("action") or raw_action.get("action_type") or raw_action.get("type")
    if not isinstance(action_name, str) or not action_name.strip():
        return None

    action: dict[str, Any] = {"action": action_name.strip().lower()}
    for key in ("target", "consumable", "item"):
        if key in raw_action and raw_action[key] is not None:
            action[key] = raw_action[key]
    return action


def _normalize_message(raw_message: Any) -> dict[str, Any] | None:
    if not isinstance(raw_message, dict):
        return None

    recipient = raw_message.get("recipient") or raw_message.get("to") or raw_message.get("target")
    content = raw_message.get("content") or raw_message.get("message")
    if not isinstance(recipient, str) or not recipient.strip():
        return None
    if not isinstance(content, str) or not content.strip():
        return None

    return {
        "recipient": recipient.strip(),
        "content": content.strip()[: config.MAX_AGENT_MESSAGE_CHARS],
    }
