from time import sleep
from typing import Any
import logging
import random

from .map import Map, Tile
from .types import *
from .agent import Agent
from .action import Action, ActionType, execute_action, valid_action
from .coordinator import send_states_to_agents
from common.replay_store import ReplayStore
from common.logging_config import color_delta, demo_log
from server.config import REPLAY_DB_PATH, SIM_MAX_TICKS


logger = logging.getLogger(__name__)
_REPLAY_STORE: ReplayStore | None = None

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
        self.max_ticks = SIM_MAX_TICKS
        self.game_over = False
        self.end_reason: str | None = None
        self.ended_tick: int | None = None
        self.action_counts: dict[int, dict[str, int]] = {agent.id: {} for agent in agents}
        self.kill_log: list[dict[str, Any]] = []
        self.death_log: list[dict[str, Any]] = []
        self.trade_log: list[dict[str, Any]] = []
        self.event_log: list[dict[str, Any]] = []
        self.active_events: list[dict[str, Any]] = []
        self.pending_trade_offers: list[dict[str, Any]] = []
        self.replay_store = _replay_store()
        self._demo_previous_agents: dict[int, dict[str, Any]] = {}
        self._demo_previous_temp: float | None = None
        self._persist_simulation("running")
        self._persist_tick("created")

    @property
    def phase(self) -> str:
        return _phase_for_tick(self.iteration)

    def run(self):
        while not self.game_over and self.iteration < self.max_ticks:
            self.tick()
            if self.game_over:
                break
            self.iteration += 1

    def tick(self):
        if self.game_over:
            return

        self._sync_agent_metrics()
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
        self._persist_tick("start")

        # create state prompt for agents and send it
        send_states_to_agents(self)
        # sleep for 1 min
        logger.info("waiting for actions sim_id=%s tick=%s seconds=60", self.id, self.iteration)
        sleep(60)
        # actions must have been received... continue with processing

        self.pending_trade_offers = []
        self.rng.shuffle(self.agents)
        for agent in self.agents:
            self.pre_action_effects(agent)
            self.process_actions(agent)
            self.base_effects(agent)

        self._finish_if_terminal()
        if not self.game_over:
            self.setup_next_iteration()
            self._finish_if_max_ticks()

        logger.info(
            "tick end sim_id=%s tick=%s temp=%.2f agents=%s",
            self.id,
            self.iteration,
            self.temp,
            [_agent_snapshot(agent) for agent in self.agents],
        )

        if self.game_over:
            logger.info("simulation ended sim_id=%s tick=%s reason=%s results=%s", self.id, self.iteration, self.end_reason, self.results())
            demo_log(logger, self.results_text())
            self._persist_simulation("finished")
            send_states_to_agents(self)
        else:
            self._persist_tick("end")

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


    def record_action(self, agent: Agent, action: Action):
        counts = self.action_counts.setdefault(agent.id, {})
        counts[action.action_type.value] = counts.get(action.action_type.value, 0) + 1

    def kill_agent(self, agent: Agent, cause: str, killer: Agent | None = None):
        if not agent.alive:
            return

        agent.death_tick = self.iteration
        agent.death_cause = cause
        agent.killed_by = killer.id if killer is not None else None
        agent.die()
        agent.clamp_metrics()
        self._remove_agent_from_map(agent)

        death_event = {
            "tick": self.iteration,
            "agent_id": agent.id,
            "cause": cause,
            "killed_by": killer.id if killer is not None else None,
        }
        self.death_log.append(death_event)

        if killer is not None and killer is not agent:
            kill_event = {
                "tick": self.iteration,
                "killer_id": killer.id,
                "victim_id": agent.id,
                "cause": cause,
            }
            self.kill_log.append(kill_event)
            demo_log(logger, "%s killed %s", _agent_label(killer), _agent_label(agent))
            self.record_event(
                f"{_agent_label(killer)} killed {_agent_label(agent)}",
                event_type="kill",
                x=killer.pos_x,
                y=killer.pos_y,
            )
        else:
            demo_log(logger, "%s died (%s)", _agent_label(agent), cause)
            self.record_event(
                f"{_agent_label(agent)} died ({cause})",
                event_type="death",
                x=agent.pos_x,
                y=agent.pos_y,
            )

    def enforce_agent_bounds(self, agent: Agent, cause: str = "health_depleted"):
        agent.recalculate_inventory()
        if not agent.alive:
            agent.clamp_metrics()
            return

        death_cause = None
        if agent.health <= 0:
            death_cause = _death_cause(agent) or cause
        agent.clamp_metrics()
        if death_cause is not None:
            self.kill_agent(agent, death_cause)
        elif agent.alive:
            _update_action_budget(agent)

    def results(self) -> dict[str, Any]:
        scoreboard = self.scoreboard()
        winners = _winner_ids(scoreboard, self.end_reason)
        return {
            "game_over": self.game_over,
            "sim_id": self.id,
            "ended_tick": self.ended_tick,
            "end_reason": self.end_reason,
            "winners": winners,
            "leaderboard": scoreboard,
            "deaths": list(self.death_log),
            "kills": list(self.kill_log),
            "trades": list(self.trade_log),
            "events": list(self.event_log),
            "action_counts": {
                str(agent_id): dict(counts)
                for agent_id, counts in self.action_counts.items()
            },
        }

    def scoreboard(self) -> list[dict[str, Any]]:
        ended_tick = self.ended_tick if self.ended_tick is not None else self.iteration
        rows = []
        kill_counts = _kill_counts(self.kill_log)
        for agent in self.agents:
            survived_ticks = agent.death_tick if agent.death_tick is not None else ended_tick + 1
            action_counts = self.action_counts.get(agent.id, {})
            rows.append(
                {
                    "agent_id": agent.id,
                    "public_key": agent.public_key,
                    "alive": agent.alive,
                    "survived_ticks": survived_ticks,
                    "kills": kill_counts.get(agent.id, 0),
                    "actions": sum(action_counts.values()),
                    "action_counts": dict(action_counts),
                    "death_tick": agent.death_tick,
                    "death_cause": agent.death_cause,
                    "killed_by": agent.killed_by,
                }
            )

        rows.sort(
            key=lambda row: (
                row["survived_ticks"],
                1 if row["alive"] else 0,
                row["kills"],
                row["actions"],
            ),
            reverse=True,
        )
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        return rows

    def results_text(self) -> str:
        results = self.results()
        lines = [
            f"Results | tick {results['ended_tick']} | {results['end_reason']}",
            "Leaderboard:",
        ]
        for row in results["leaderboard"]:
            status = "alive" if row["alive"] else f"dead:{row['death_cause']}"
            lines.append(
                f"#{row['rank']} A{row['agent_id']} {status} "
                f"survived={row['survived_ticks']} kills={row['kills']} actions={row['actions']}"
            )

        if results["kills"]:
            lines.append("Kills:")
            for kill in results["kills"]:
                lines.append(
                    f"tick {kill['tick']}: A{kill['killer_id']} killed A{kill['victim_id']} ({kill['cause']})"
                )

        if results["trades"]:
            lines.append("Trades:")
            for trade in results["trades"]:
                lines.append(
                    f"tick {trade['tick']}: A{trade['from_agent_id']} traded "
                    f"{trade['offered']} with A{trade['to_agent_id']} for {trade['requested']}"
                )

        if results["deaths"]:
            lines.append("Deaths:")
            for death in results["deaths"]:
                killer = "" if death["killed_by"] is None else f" by A{death['killed_by']}"
                lines.append(f"tick {death['tick']}: A{death['agent_id']} died{killer} ({death['cause']})")

        lines.append("Actions:")
        for row in sorted(results["leaderboard"], key=lambda item: item["agent_id"]):
            counts = row["action_counts"]
            count_text = ", ".join(f"{name}={count}" for name, count in sorted(counts.items())) or "none"
            lines.append(f"A{row['agent_id']}: {count_text}")
        return "\n".join(lines)

    def _finish_if_terminal(self):
        alive_agents = [agent for agent in self.agents if agent.alive]
        if len(self.agents) > 1 and len(alive_agents) <= 1:
            reason = "last_agent_standing" if alive_agents else "all_agents_dead"
            self._end(reason)

    def _finish_if_max_ticks(self):
        if self.iteration + 1 >= self.max_ticks:
            self._end("max_ticks_reached")

    def _end(self, reason: str):
        if self.game_over:
            return
        self._sync_agent_metrics()
        self.game_over = True
        self.end_reason = reason
        self.ended_tick = self.iteration
        for agent in self.agents:
            if agent.alive:
                _update_action_budget(agent)

    def _sync_agent_metrics(self):
        for agent in self.agents:
            agent.recalculate_inventory()
            agent.clamp_metrics()
            if agent.alive:
                _update_action_budget(agent)

    def _remove_agent_from_map(self, agent: Agent):
        for row in self.map.grid:
            for tile in row:
                if agent in tile.occupants:
                    tile.occupants.remove(agent)


    def record_event(
        self,
        message: str,
        *,
        event_type: str,
        x: int | None = None,
        y: int | None = None,
    ):
        event = {
            "tick": self.iteration,
            "type": event_type,
            "message": message,
            "x": x,
            "y": y,
        }
        self.event_log.append(event)
        if self.replay_store is not None:
            self.replay_store.record_event(
                self.id,
                self.iteration,
                event_type,
                message,
                event,
            )
        demo_log(logger, message)


    def pre_action_effects(self, agent: Agent):
        pass

    def process_actions(self, agent: Agent):
        if not agent.alive:
            return

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
            self.record_action(agent, action)
            self.enforce_agent_bounds(agent)
            for other_agent in self.agents:
                if other_agent is not agent:
                    self.enforce_agent_bounds(other_agent)
            after = _agent_snapshot(agent)
            self._persist_action(agent, action, before, after)
            demo_log(logger, _demo_action_line(self, agent, action))
            logger.info(
                "action result sim_id=%s tick=%s agent=%s before=%s after=%s remaining_budget=%.2f",
                self.id,
                self.iteration,
                agent.id,
                before,
                after,
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
        hazard = getattr(current_tile, "hazard", None)
        phase = self.phase

        # hunger and thirst increase
        agent.hunger = min(100, agent.hunger + 10)
        agent.thirst = min(100, agent.thirst + 10)

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
            if phase == "night":
                agent.warmth -= 2

        if phase == "day":
            agent.mental_health = min(100, agent.mental_health + 0.5)
        if agent.inventory.get(ResourceType.CLOTHING, 0) > 0:
            agent.warmth = min(100, agent.warmth + 1)

        if hazard == "snowstorm" and not in_own_shelter:
            agent.warmth -= 6
            agent.mental_health -= 2
        elif hazard == "disease_outbreak" and self.rng.random() < 0.08:
            was_sick = "sick" in agent.status
            agent.add_status("sick", self.iteration)
            if not was_sick:
                self.record_event(
                    f"{_agent_label(agent)} got sick",
                    event_type="sickness",
                    x=agent.pos_x,
                    y=agent.pos_y,
                )

        if "sick" in agent.status:
            agent.health -= 2
            agent.thirst = min(100, agent.thirst + 3)
            if agent.status_age("sick", self.iteration) >= 6 and agent.health > 50 and agent.thirst < 70:
                if self.rng.random() < 0.25:
                    agent.remove_status("sick")
                    self.record_event(
                        f"{_agent_label(agent)} recovered from sickness",
                        event_type="recovery",
                        x=agent.pos_x,
                        y=agent.pos_y,
                    )

        if agent.warmth < 30:
            agent.health -= (30 - agent.warmth) * 0.5

        load_pressure = _load_pressure(agent)
        if load_pressure > 0:
            agent.thirst = min(100, agent.thirst + 2 * load_pressure)
            agent.hunger = min(100, agent.hunger + 2 * load_pressure)
        
        self.enforce_agent_bounds(agent, _death_cause(agent) or "health_depleted")

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
        self._advance_world_events(next_iteration)
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
                for trap in getattr(tile, "traps", []):
                    if trap.get("ready_iteration") == next_iteration:
                        logger.info(
                            "trap ready sim_id=%s tick=%s tile=(%s,%s) trap=%s",
                            self.id,
                            self.iteration,
                            tile.pos_x,
                            tile.pos_y,
                            trap,
                        )

        # update temp
        previous_temp = self.temp
        temp_delta = -0.5 * self.rng.random()
        if self._active_event("cold_snap") or self._active_event("snowstorm"):
            temp_delta -= 1.0
        elif self._active_event("rain"):
            temp_delta -= 0.2
        self.temp = self.temp + temp_delta
        logger.info(
            "next iteration setup sim_id=%s tick=%s next_tick=%s temp %.2f -> %.2f",
            self.id,
            self.iteration,
            next_iteration,
            previous_temp,
            self.temp,
        )

    def _advance_world_events(self, next_iteration: int):
        self.active_events = [
            event
            for event in self.active_events
            if event.get("ends_iteration", 0) > next_iteration
        ]
        self._clear_tile_hazards()

        if self.rng.random() < 0.16:
            self._start_random_event(next_iteration)

        for event in self.active_events:
            if event["type"] in {"snowstorm", "disease_outbreak"}:
                self._mark_hazard(event)

    def _start_random_event(self, next_iteration: int):
        event_type = self.rng.choices(
            ["rain", "cold_snap", "snowstorm", "supply_drop", "disease_outbreak"],
            weights=[4, 3, 2, 2, 1],
            k=1,
        )[0]
        if event_type == "supply_drop":
            tile = self._random_passable_tile()
            if tile is None:
                return
            tile.resources[ResourceType.PROCESSED_FOOD] += self.rng.randint(1, 3)
            tile.resources[ResourceType.CLEAN_WATER] += self.rng.randint(1, 3)
            if self.rng.random() < 0.5:
                tile.resources[ResourceType.LIGHT_MEDS] += 1
            self.record_event(
                f"Supply drop lands at ({tile.pos_x},{tile.pos_y})",
                event_type="supply_drop",
                x=tile.pos_x,
                y=tile.pos_y,
            )
            return

        duration = self.rng.randint(2, 4)
        event = {
            "type": event_type,
            "started_iteration": next_iteration,
            "ends_iteration": next_iteration + duration,
        }
        if event_type in {"snowstorm", "disease_outbreak"}:
            tile = self._random_passable_tile()
            if tile is None:
                return
            radius = self.rng.randint(2, 3) if event_type == "snowstorm" else 1
            event.update({"x": tile.pos_x, "y": tile.pos_y, "radius": radius})
        self.active_events.append(event)

        location = ""
        if "x" in event:
            location = f" near ({event['x']},{event['y']})"
        self.record_event(
            f"{event_type.replace('_', ' ')} begins{location}",
            event_type=event_type,
            x=event.get("x"),
            y=event.get("y"),
        )

    def _random_passable_tile(self) -> Tile | None:
        candidates = [
            tile
            for row in self.map.grid
            for tile in row
            if tile.type not in (TileType.WATER, TileType.MOUNTAIN)
        ]
        if not candidates:
            return None
        return self.rng.choice(candidates)

    def _clear_tile_hazards(self):
        for row in self.map.grid:
            for tile in row:
                tile.hazard = None

    def _mark_hazard(self, event: dict[str, Any]):
        x = event.get("x")
        y = event.get("y")
        radius = int(event.get("radius", 0))
        if not isinstance(x, int) or not isinstance(y, int):
            return
        for row in self.map.grid:
            for tile in row:
                if abs(tile.pos_x - x) <= radius and abs(tile.pos_y - y) <= radius:
                    tile.hazard = event["type"]

    def _active_event(self, event_type: str) -> bool:
        return any(event["type"] == event_type for event in self.active_events)

    def snapshot(self) -> dict[str, Any]:
        return {
            "sim_id": self.id,
            "seed": self.seed,
            "tick": self.iteration,
            "phase": self.phase,
            "temp": round(self.temp, 2),
            "game_over": self.game_over,
            "end_reason": self.end_reason,
            "ended_tick": self.ended_tick,
            "max_ticks": self.max_ticks,
            "alive_count": sum(1 for agent in self.agents if agent.alive),
            "agents": [_agent_snapshot(agent) for agent in sorted(self.agents, key=lambda item: item.id)],
            "map": _map_snapshot(self.map),
            "active_events": list(self.active_events),
            "recent_events": list(self.event_log[-24:]),
            "recent_trades": list(self.trade_log[-24:]),
            "scoreboard": self.scoreboard(),
            "results": self.results() if self.game_over else None,
        }

    def _persist_simulation(self, status: str):
        if self.replay_store is None:
            return
        self.replay_store.upsert_simulation(
            self.id,
            seed=self.seed,
            status=status,
            summary=self.snapshot(),
        )

    def _persist_tick(self, kind: str):
        if self.replay_store is None:
            return
        self.replay_store.record_tick(self.id, self.iteration, kind, self.snapshot())

    def _persist_action(
        self,
        agent: Agent,
        action: Action,
        before: dict[str, Any],
        after: dict[str, Any],
    ):
        if self.replay_store is None:
            return
        self.replay_store.record_action(
            self.id,
            self.iteration,
            agent.id,
            action.to_dict(),
            {"before": before, "after": after},
        )


def _agent_snapshot(agent: Agent) -> dict[str, Any]:
    agent.recalculate_inventory()
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
        "status_since": dict(agent.status_since),
        "inventory": {
            str(resource): amount
            for resource, amount in agent.inventory.items()
            if amount > 0
        },
        "inventory_weight": agent.inventory_weight,
        "carry_capacity": agent.carry_capacity,
        "reputation": round(agent.reputation, 2),
        "trust": {str(agent_id): round(value, 2) for agent_id, value in agent.trust.items()},
        "grudges": {str(agent_id): round(value, 2) for agent_id, value in agent.grudges.items()},
        "death_tick": agent.death_tick,
        "death_cause": agent.death_cause,
        "killed_by": agent.killed_by,
    }


def _map_snapshot(map_obj: Map) -> list[list[dict[str, Any]]]:
    rows = []
    for row in map_obj.grid:
        rows.append([_tile_snapshot(tile) for tile in row])
    return rows


def _tile_snapshot(tile: Tile) -> dict[str, Any]:
    return {
        "x": tile.pos_x,
        "y": tile.pos_y,
        "type": tile.type.value,
        "occupants": [agent.id for agent in tile.occupants if agent.alive],
        "resources": {
            str(resource): amount
            for resource, amount in tile.resources.items()
            if amount > 0
        },
        "shelters": list(tile.shelters.keys()),
        "storages": {
            owner: {
                str(resource): amount
                for resource, amount in storage.items()
                if amount > 0
            }
            for owner, storage in tile.storages.items()
        },
        "crops": [crop.copy() for crop in tile.crops],
        "traps": [trap.copy() for trap in getattr(tile, "traps", [])],
        "hazard": tile.hazard,
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
    status = "" if agent.alive else f" dead:{agent.death_cause}"
    return (
        f"{_agent_label(agent)} pos=({agent.pos_x},{agent.pos_y}) "
        f"hp={health} hunger={hunger} thirst={thirst} warmth={warmth}{status}"
    )


def _demo_action_line(sim, agent: Agent, action: Action) -> str:
    target = _target_text(action.target)
    consumable = _plain_value(action.consumable)
    item = _plain_value(action.item)

    if action.action_type == ActionType.WAIT:
        return f"{_agent_label(agent)} waits"
    if action.action_type == ActionType.REST:
        return f"{_agent_label(agent)} rests"
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
    if action.action_type == ActionType.PURIFY_WATER:
        return f"{_agent_label(agent)} purifies water with {item}"
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
    if action.action_type == ActionType.CRAFT_FISHING_ROD:
        return f"{_agent_label(agent)} crafts a fishing rod"
    if action.action_type == ActionType.CRAFT_TRAP:
        return f"{_agent_label(agent)} crafts a trap"
    if action.action_type == ActionType.SET_TRAP:
        return f"{_agent_label(agent)} sets a trap"
    if action.action_type == ActionType.HARVEST_TRAP:
        return f"{_agent_label(agent)} harvests a trap"
    if action.action_type == ActionType.TRADE:
        return (
            f"{_agent_label(agent)} offers {consumable} to {_target_agent_label(sim, action.target)} "
            f"for {item}"
        )

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


def _death_cause(agent: Agent) -> str | None:
    if agent.warmth <= 0:
        return "exposure"
    if agent.health > 0:
        return None
    if agent.thirst >= 100:
        return "dehydration"
    if agent.hunger >= 100:
        return "starvation"
    if agent.warmth < 30:
        return "exposure"
    return "health_depleted"


def _phase_for_tick(tick: int) -> str:
    hour = (6 + tick * 2) % 24
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "day"
    if 17 <= hour < 21:
        return "evening"
    return "night"


def _load_pressure(agent: Agent) -> float:
    if agent.carry_capacity <= 0:
        return 0.0
    load_ratio = agent.inventory_weight / agent.carry_capacity
    return max(0.0, min(1.0, (load_ratio - 0.65) / 0.35))


def _update_action_budget(agent: Agent):
    if not agent.alive:
        agent.action_budget = 0
    elif agent.mental_health < 20:
        agent.action_budget = 0.5
    elif agent.mental_health < 70:
        agent.action_budget = 0.8
    else:
        agent.action_budget = 1.0


def _kill_counts(kill_log: list[dict[str, Any]]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for kill in kill_log:
        killer_id = kill.get("killer_id")
        if isinstance(killer_id, int):
            counts[killer_id] = counts.get(killer_id, 0) + 1
    return counts


def _winner_ids(scoreboard: list[dict[str, Any]], end_reason: str | None) -> list[int]:
    if not scoreboard:
        return []
    if end_reason == "all_agents_dead":
        return []
    if end_reason == "last_agent_standing":
        return [
            row["agent_id"]
            for row in scoreboard
            if row.get("alive")
        ]

    best = scoreboard[0]
    return [
        row["agent_id"]
        for row in scoreboard
        if (
            row["survived_ticks"],
            row["kills"],
            row["actions"],
        ) == (
            best["survived_ticks"],
            best["kills"],
            best["actions"],
        )
    ]


def _replay_store() -> ReplayStore | None:
    global _REPLAY_STORE
    if not REPLAY_DB_PATH:
        return None
    if _REPLAY_STORE is None:
        _REPLAY_STORE = ReplayStore(REPLAY_DB_PATH)
    return _REPLAY_STORE
