from __future__ import annotations

import json
from typing import Any
from urllib import error, request

from . import config


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


SYSTEM_PROMPT = """
You are choosing one turn for a survival simulation agent.
Return only JSON that matches the provided schema.
Choose actions from the valid_actions list in the prompt.
Preserve action names, target objects, consumables, and items exactly as shown in valid_actions.
Use messages only when you also choose a valid talk_to action for the same recipient public key.
Do not include explanations, markdown, or keys outside the schema.
"""


def get_llm_response(prompt: str) -> dict[str, list[dict[str, Any]]]:
    try:
        payload = _create_chat_payload(prompt)
        base_url = config.OLLAMA_BASE_URL.rstrip("/")
        response = _post_json(f"{base_url}/api/chat", payload)
        content = _extract_chat_content(response)
        parsed = _parse_json_content(content)
        return normalize_llm_response(parsed)
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError, error.URLError) as exc:
        print(f"Ollama request failed, falling back to wait: {exc}")
        return {"actions": [{"action": "wait"}], "messages": []}


def normalize_llm_response(payload: Any) -> dict[str, list[dict[str, Any]]]:
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
        "stream": False,
        "format": ACTION_RESPONSE_SCHEMA,
        "think": config.OLLAMA_THINK,
        "keep_alive": config.OLLAMA_KEEP_ALIVE,
        "options": options,
    }


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with request.urlopen(req, timeout=config.OLLAMA_TIMEOUT_SECONDS) as resp:
        response_body = resp.read().decode("utf-8")
    return json.loads(response_body)


def _extract_chat_content(response: dict[str, Any]) -> str:
    message = response.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    raise ValueError("Ollama response missing message.content")


def _parse_json_content(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(content[start : end + 1])


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
