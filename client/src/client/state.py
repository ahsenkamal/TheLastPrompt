import json

class State:
    def __init__(self, sim_state):
        self.state_history = []
        self.sim_state = sim_state
        self.state_history.append(self.sim_state)

    def update(self, sim_state):
        self.state_history.append(self.sim_state)
        self.sim_state = sim_state

    def get_state_description(self):
        return json.dumps(self.sim_state, indent=2, ensure_ascii=False)
