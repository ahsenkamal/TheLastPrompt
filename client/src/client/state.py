import json
from copy import deepcopy
from typing import Any

class State:
    def __init__(self, sim_state):
        self.state_history = []
        self.sim_state = sim_state
        self.agent_messages: list[dict[str, Any]] = []
        self.state_history.append(self.sim_state)

    def update(self, sim_state):
        self.state_history.append(self.sim_state)
        self.sim_state = sim_state

    @property
    def tick(self) -> int:
        return int(self.sim_state.get("tick", 0))

    def set_agent_messages(self, messages: list[dict[str, Any]]):
        self.agent_messages = messages

    def get_valid_actions(self) -> list[dict[str, Any]]:
        valid_actions = self.sim_state.get("valid_actions", [])
        if isinstance(valid_actions, list):
            return [action for action in valid_actions if isinstance(action, dict)]
        return []

    def get_state_description(self):
        state = deepcopy(self.sim_state)
        state["incoming_agent_messages"] = self.agent_messages
        state["state_history_length"] = len(self.state_history)
        return json.dumps(state, indent=2, ensure_ascii=False)
