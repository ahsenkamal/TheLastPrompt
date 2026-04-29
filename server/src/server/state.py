class State:
    def __init__(self, sim_size, self_public_key):
        self.matchmaking_queue = []
        self.sim_instances = []
        self.sim_size = sim_size
        self.self_public_key = self_public_key

    def add_to_queue(self, agent_public_key):
        self.matchmaking_queue.append(agent_public_key)

    def queue_ready(self):
        return len(self.matchmaking_queue) >= self.sim_size

    def pick_new_sim_agents(self):
        agents = self.matchmaking_queue[:self.sim_size]
        self.matchmaking_queue = self.matchmaking_queue[self.sim_size:]
        return agents
