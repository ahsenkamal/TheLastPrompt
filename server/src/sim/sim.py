from time import sleep
from typing import Any
import logging
import random

from .map import Map, Tile
from .types import *
from .agent import Agent
from .action import Action, execute_action, valid_action
from .coordinator import send_states_to_agents


logger = logging.getLogger(__name__)

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
        logger.info(
            "tick start sim_id=%s tick=%s temp=%.2f agents=%s",
            self.id,
            self.iteration,
            self.temp,
            [_agent_snapshot(agent) for agent in self.agents],
        )
        logger.info("tick map sim_id=%s tick=%s\n%s", self.id, self.iteration, self.map.render())
        logger.info("tick resources sim_id=%s tick=%s\n%s", self.id, self.iteration, self.map.render_resources())

        # create state prompt for agents and send it
        send_states_to_agents(self)
        # sleep for 1 min
        logger.info("waiting for actions sim_id=%s tick=%s seconds=60", self.id, self.iteration)
        sleep(60)
        # actions must have been received... continue with processing

        self.rng.shuffle(self.agents)
        for agent in self.agents:
            self.pre_action_effects(agent)
            self.process_actions(agent)
            self.base_effects(agent)

        self.setup_next_iteration()
        logger.info(
            "tick end sim_id=%s tick=%s temp=%.2f agents=%s",
            self.id,
            self.iteration,
            self.temp,
            [_agent_snapshot(agent) for agent in self.agents],
        )


    def pre_action_effects(self, agent: Agent):
        pass

    def process_actions(self, agent: Agent):
        actions = agent.pop_actions(self.iteration)
        remaining_budget = agent.action_budget
        executed_action = False
        logger.info(
            "processing actions sim_id=%s tick=%s agent=%s queued=%s actions=%s",
            self.id,
            self.iteration,
            agent.id,
            len(actions),
            [_action_payload(action) for action in actions],
        )

        for raw_action in actions:
            try:
                action = Action.from_dict(raw_action)
            except (TypeError, ValueError) as exc:
                logger.warning(
                    "discard invalid action sim_id=%s tick=%s agent=%s payload=%s error=%s",
                    self.id,
                    self.iteration,
                    agent.id,
                    raw_action,
                    exc,
                )
                continue

            if not valid_action(self, agent, action):
                logger.warning(
                    "discard unavailable action sim_id=%s tick=%s agent=%s action=%s",
                    self.id,
                    self.iteration,
                    agent.id,
                    action.to_dict(),
                )
                continue

            if action.budget > remaining_budget:
                logger.info(
                    "skip action over budget sim_id=%s tick=%s agent=%s action=%s remaining_budget=%.2f",
                    self.id,
                    self.iteration,
                    agent.id,
                    action.to_dict(),
                    remaining_budget,
                )
                continue

            before = _agent_snapshot(agent)
            logger.info(
                "execute action sim_id=%s tick=%s agent=%s action=%s remaining_budget=%.2f",
                self.id,
                self.iteration,
                agent.id,
                action.to_dict(),
                remaining_budget,
            )
            execute_action(self, agent, action)
            remaining_budget -= action.budget
            executed_action = True
            logger.info(
                "action result sim_id=%s tick=%s agent=%s before=%s after=%s remaining_budget=%.2f",
                self.id,
                self.iteration,
                agent.id,
                before,
                _agent_snapshot(agent),
                remaining_budget,
            )

        if actions and not executed_action:
            logger.info(
                "no valid actions executed; fallback to wait sim_id=%s tick=%s agent=%s",
                self.id,
                self.iteration,
                agent.id,
            )

    def base_effects(self, agent: Agent):
        if not agent.alive:
            logger.info(
                "skip base effects dead agent sim_id=%s tick=%s agent=%s",
                self.id,
                self.iteration,
                agent.id,
            )
            return

        before = _agent_snapshot(agent)
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

        logger.info(
            "base effects sim_id=%s tick=%s agent=%s in_own_shelter=%s before=%s after=%s",
            self.id,
            self.iteration,
            agent.id,
            in_own_shelter,
            before,
            _agent_snapshot(agent),
        )

    def setup_next_iteration(self):
        next_iteration = self.iteration + 1
        for row in self.map.grid:
            for tile in row:
                for crop in list(tile.crops):
                    if crop["ready_iteration"] <= next_iteration:
                        tile.resources[ResourceType.RAW_FOOD] += 3
                        tile.crops.remove(crop)
                        logger.info(
                            "crop ready sim_id=%s tick=%s tile=(%s,%s) raw_food_added=3 crop=%s",
                            self.id,
                            self.iteration,
                            tile.pos_x,
                            tile.pos_y,
                            crop,
                        )

        # update temp
        previous_temp = self.temp
        self.temp = self.temp - 0.5 * self.rng.random()
        logger.info(
            "next iteration setup sim_id=%s tick=%s next_tick=%s temp %.2f -> %.2f",
            self.id,
            self.iteration,
            next_iteration,
            previous_temp,
            self.temp,
        )


def _agent_snapshot(agent: Agent) -> dict[str, Any]:
    return {
        "id": agent.id,
        "public_key": agent.public_key,
        "alive": agent.alive,
        "pos": {"x": agent.pos_x, "y": agent.pos_y},
        "health": round(agent.health, 2),
        "mental_health": round(agent.mental_health, 2),
        "hunger": round(agent.hunger, 2),
        "thirst": round(agent.thirst, 2),
        "warmth": round(agent.warmth, 2),
        "strength": agent.strength,
        "stance": agent.stance,
        "status": list(agent.status),
        "inventory": {
            str(resource): amount
            for resource, amount in agent.inventory.items()
            if amount > 0
        },
    }


def _action_payload(action: Any) -> Any:
    if isinstance(action, Action):
        return action.to_dict()
    return action
