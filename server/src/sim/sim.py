from time import sleep
from typing import Any
import logging
import random

from .map import Map, Tile
from .types import *
from .agent import Agent
from .action import Action, ActionType, execute_action, valid_action
from .coordinator import send_states_to_agents
from common.logging_config import color_delta, demo_log


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
        self._demo_previous_agents: dict[int, dict[str, Any]] = {}
        self._demo_previous_temp: float | None = None

    def run(self):
        for i in range(100):
            self.tick()
            self.iteration += 1

    def tick(self):
        self._log_demo_tick_start()
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

    def _log_demo_tick_start(self):
        temp = color_delta(self.temp, self._demo_previous_temp)
        lines = [
            f"Tick {self.iteration} | temp {temp}C",
            self.map.render_demo(),
            "Agents:",
        ]
        for agent in sorted(self.agents, key=lambda item: item.id):
            lines.append(_demo_agent_stats(agent, self._demo_previous_agents.get(agent.id)))
        lines.append("Actions:")
        demo_log(logger, "\n".join(lines))

        self._demo_previous_temp = self.temp
        self._demo_previous_agents = {
            agent.id: _agent_snapshot(agent)
            for agent in self.agents
        }


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
            demo_log(logger, _demo_action_line(self, agent, action))
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
            demo_log(logger, "%s waits", _agent_label(agent))
        elif not actions:
            demo_log(logger, "%s waits", _agent_label(agent))

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


def _demo_agent_stats(agent: Agent, previous: dict[str, Any] | None) -> str:
    previous = previous or {}
    health = color_delta(agent.health, previous.get("health"))
    hunger = color_delta(agent.hunger, previous.get("hunger"), lower_is_better=True)
    thirst = color_delta(agent.thirst, previous.get("thirst"), lower_is_better=True)
    warmth = color_delta(agent.warmth, previous.get("warmth"))
    return (
        f"{_agent_label(agent)} pos=({agent.pos_x},{agent.pos_y}) "
        f"hp={health} hunger={hunger} thirst={thirst} warmth={warmth}"
    )


def _demo_action_line(sim, agent: Agent, action: Action) -> str:
    target = _target_text(action.target)
    consumable = _plain_value(action.consumable)
    item = _plain_value(action.item)

    if action.action_type == ActionType.WAIT:
        return f"{_agent_label(agent)} waits"
    if action.action_type == ActionType.SLEEP:
        return f"{_agent_label(agent)} sleeps"
    if action.action_type == ActionType.EAT:
        return f"{_agent_label(agent)} eats {consumable}"
    if action.action_type == ActionType.DRINK:
        return f"{_agent_label(agent)} drinks {consumable}"
    if action.action_type == ActionType.HEAL:
        return f"{_agent_label(agent)} heals with {consumable}"
    if action.action_type == ActionType.TALK_TO:
        return f"{_agent_label(agent)} talks to {_target_agent_label(sim, action.target)}"
    if action.action_type == ActionType.WARMUP:
        return f"{_agent_label(agent)} warms up with {consumable}"
    if action.action_type == ActionType.TRAIN:
        return f"{_agent_label(agent)} trains"
    if action.action_type == ActionType.CHANGE_STANCE:
        return f"{_agent_label(agent)} switches stance to {target}"
    if action.action_type == ActionType.MOVE:
        return f"{_agent_label(agent)} moves to {target}"
    if action.action_type == ActionType.CHANGE_STATUS:
        return f"{_agent_label(agent)} switches status to {target}"
    if action.action_type == ActionType.CREATE_SHELTER:
        return f"{_agent_label(agent)} builds shelter at {target}"
    if action.action_type == ActionType.ATTACK:
        return f"{_agent_label(agent)} attacks {_target_agent_label(sim, action.target)}"
    if action.action_type == ActionType.GROW_FOOD:
        return f"{_agent_label(agent)} plants food at {target}"
    if action.action_type == ActionType.COOK_FOOD:
        return f"{_agent_label(agent)} cooks {consumable} with {item}"
    if action.action_type == ActionType.STEAL:
        return f"{_agent_label(agent)} steals at {target}"
    if action.action_type == ActionType.CREATE_STORAGE:
        return f"{_agent_label(agent)} builds storage at {target}"
    if action.action_type == ActionType.GATHER_WOOD:
        return f"{_agent_label(agent)} gathers wood at {target}"
    if action.action_type == ActionType.PICK_RESOURCE:
        return f"{_agent_label(agent)} picks up {consumable}"
    if action.action_type == ActionType.FISH:
        return f"{_agent_label(agent)} fishes at {target}"
    if action.action_type == ActionType.TRADE:
        return f"{_agent_label(agent)} trades with {_target_agent_label(sim, action.target)}"

    return f"{_agent_label(agent)} does {action.action_type.value}"


def _target_agent_label(sim, target: Any) -> str:
    target_agent = _find_agent_for_demo(sim, target)
    if target_agent is not None:
        return _agent_label(target_agent)
    return _target_text(target)


def _find_agent_for_demo(sim, target: Any) -> Agent | None:
    if isinstance(target, Agent):
        return target

    target_id = None
    target_public_key = None
    if isinstance(target, dict):
        target_id = target.get("id")
        target_public_key = target.get("public_key")
    elif isinstance(target, int):
        target_id = target
    elif isinstance(target, str):
        target_public_key = target

    for agent in sim.agents:
        if target_id is not None and agent.id == target_id:
            return agent
        if target_public_key is not None and agent.public_key == target_public_key:
            return agent
    return None


def _target_text(target: Any) -> str:
    if isinstance(target, dict):
        if "x" in target and "y" in target:
            return f"({target['x']},{target['y']})"
        if "id" in target:
            return f"A{target['id']}"
    return str(_plain_value(target))


def _plain_value(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _agent_label(agent: Agent | None) -> str:
    if agent is None:
        return "A?"
    return f"A{agent.id}"
