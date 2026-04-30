from time import sleep

from .map import Map, Tile
from .types import *
from .agent import Agent
from .action import Action, execute_action, valid_action
from .coordinator import send_states_to_agents 
import random

class Simulation:
    def __init__(self, sim_id, map: Map, agents: list[Agent], seed: int):
        self.id = sim_id
        self.map = map
        self.agents = agents
        self.iteration = 0
        self.temp = 15.0
        self.seed = seed
        self.rng = random.Random(seed)
        self.future = None

    def run(self):
        for i in range(100):
            self.tick()
            self.iteration += 1
    
    def tick(self):
        # create state prompt for agents and send it
        send_states_to_agents(self)
        # sleep for 1 min
        sleep(60)
        # actions must have been received... continue with processing

        self.rng.shuffle(self.agents)
        for agent in self.agents:
            self.pre_action_effects(agent)
            self.process_actions(agent)
            self.base_effects(agent)

        self.setup_next_iteration()
    

    def pre_action_effects(self, agent: Agent):
        pass

    def process_actions(self, agent: Agent):
        actions = agent.pop_actions(self.iteration)
        remaining_budget = agent.action_budget
        for action in actions:
            try:
                action = Action.from_dict(action)
            except (TypeError, ValueError):
                continue
            if valid_action(self, agent, action):
                if action.budget > remaining_budget:
                    continue
                execute_action(self, agent, action)
                remaining_budget -= action.budget

    def base_effects(self, agent: Agent):
        if not agent.alive:
            return

        current_tile = self.map.grid[agent.pos_y][agent.pos_x]
        in_own_shelter = agent.public_key in getattr(current_tile, "shelters", {})
        
        # hunger and thirst increase
        agent.hunger += 10
        agent.thirst += 10

        # health decrease if hunger or thirst is too high
        if agent.hunger > 70:
            agent.health -= (agent.hunger - 50) * 0.1
        if agent.thirst > 50:
            agent.health -= (agent.thirst - 50) * 0.2
        
        # mental health decrease if hunger or thirst is too high
        if agent.hunger > 70:
            agent.mental_health -= (agent.hunger - 70) * 0.1
        if agent.thirst > 70:
            agent.mental_health -= (agent.thirst - 70) * 0.1

        # mental health below 20 causes reduced action budget 0.5
        # mental health below 70 action budget 0.8
        # mental health 100 action budget 1

        if in_own_shelter:
            agent.mental_health = min(100, agent.mental_health + 2)
        else:
            # warmth decrease if temp is low
            if self.temp <= 0:
                agent.warmth -= abs(self.temp) * 0.5
            else:
                agent.warmth -= self.temp * 0.1

        if agent.warmth < 30:
            agent.health -= (30 - agent.warmth) * 0.5
        
        # check if agent is dead
        if agent.health <= 0 or agent.warmth <= 0:
            agent.die()

    
    def setup_next_iteration(self):
        next_iteration = self.iteration + 1
        for row in self.map.grid:
            for tile in row:
                for crop in list(tile.crops):
                    if crop["ready_iteration"] <= next_iteration:
                        tile.resources[ResourceType.RAW_FOOD] += 3
                        tile.crops.remove(crop)

        # update temp
        self.temp = self.temp - 0.5 * self.rng.random()
