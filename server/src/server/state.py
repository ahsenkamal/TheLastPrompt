from typing import TYPE_CHECKING, Any

from common.identity import normalize_agent_profile

if TYPE_CHECKING:
    from sim.agent import Agent
    from sim.sim import Simulation


class State:
    def __init__(self, sim_size, self_public_key):
        self.matchmaking_queue = []
        self.sim_instances = []
        self.agent_profiles: dict[str, dict[str, Any]] = {}
        self.sim_size = sim_size
        self.self_public_key = self_public_key
        self.seed = 0

    def add_to_queue(self, agent_public_key, profile: dict[str, Any] | None = None):
        self.update_agent_profile(agent_public_key, profile)
        if agent_public_key in self.matchmaking_queue:
            return
        self.matchmaking_queue.append(agent_public_key)

    def update_agent_profile(self, agent_public_key: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized = normalize_agent_profile(profile, agent_public_key)
        existing = self.agent_profiles.get(agent_public_key, {})
        merged = {
            **existing,
            **{
                key: value
                for key, value in normalized.items()
                if value is not None and value != ""
            },
        }
        self.agent_profiles[agent_public_key] = merged

        for sim_instance in self.sim_instances:
            for agent in getattr(sim_instance, "agents", []):
                if getattr(agent, "public_key", None) == agent_public_key:
                    agent.set_profile(merged)
        return merged

    def queue_ready(self):
        return len(self.matchmaking_queue) >= self.sim_size

    def pick_new_sim_agents(self):
        agents = self.matchmaking_queue[:self.sim_size]
        self.matchmaking_queue = self.matchmaking_queue[self.sim_size:]
        self.seed = (self.seed + 1) % (2**32)
        profiles = {
            agent_public_key: self.agent_profiles.get(agent_public_key, {})
            for agent_public_key in agents
        }
        return (agents, self.seed, profiles)

    def find_sim_and_agent(self, agent_public_key: str) -> tuple["Simulation", "Agent"] | None:
        ordered_sims = [
            sim_instance
            for sim_instance in self.sim_instances
            if not getattr(sim_instance, "game_over", False)
        ]
        ordered_sims.extend(
            sim_instance
            for sim_instance in self.sim_instances
            if getattr(sim_instance, "game_over", False)
        )

        for sim_instance in ordered_sims:
            agents = getattr(sim_instance, "agents", [])
            for agent in agents:
                if agent.public_key == agent_public_key:
                    return sim_instance, agent
        return None
