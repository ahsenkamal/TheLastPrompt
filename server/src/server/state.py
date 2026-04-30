from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sim.agent import Agent
    from sim.sim import Simulation


class State:
    def __init__(self, sim_size, self_public_key):
        self.matchmaking_queue = []
        self.sim_instances = []
        self.sim_size = sim_size
        self.self_public_key = self_public_key
        self.seed = 0

    def add_to_queue(self, agent_public_key):
        if agent_public_key in self.matchmaking_queue:
            return
        self.matchmaking_queue.append(agent_public_key)

    def queue_ready(self):
        return len(self.matchmaking_queue) >= self.sim_size

    def pick_new_sim_agents(self):
        agents = self.matchmaking_queue[:self.sim_size]
        self.matchmaking_queue = self.matchmaking_queue[self.sim_size:]
        self.seed = (self.seed + 1) % (2**32)
        return (agents, self.seed)

    def find_sim_and_agent(self, agent_public_key: str) -> tuple["Simulation", "Agent"] | None:
        for sim_instance in self.sim_instances:
            agents = getattr(sim_instance, "agents", [])
            for agent in agents:
                if agent.public_key == agent_public_key:
                    return sim_instance, agent
        return None
