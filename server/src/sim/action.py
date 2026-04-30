from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .agent import Agent
    from .sim import Simulation

from .types import ResourceType, TileType


class ActionType(StrEnum):
    WAIT = "wait"
    SLEEP = "sleep"
    EAT = "eat"
    DRINK = "drink"
    HEAL = "heal"
    TALK_TO = "talk_to"
    WARMUP = "warmup"
    TRAIN = "train"
    CHANGE_STANCE = "change_stance"
    MOVE = "move"
    CHANGE_STATUS = "change_status"
    CREATE_SHELTER = "create_shelter"
    ATTACK = "attack"
    GROW_FOOD = "grow_food"
    COOK_FOOD = "cook_food"
    STEAL = "steal"
    CREATE_STORAGE = "create_storage"
    GATHER_WOOD = "gather_wood"
    PICK_RESOURCE = "pick_resource"
    FISH = "fish"
    TRADE = "trade"


ACTION_BUDGETS: dict[ActionType, float] = {
    ActionType.WAIT: 0.0,
    ActionType.SLEEP: 0.5,
    ActionType.EAT: 0.2,
    ActionType.DRINK: 0.1,
    ActionType.HEAL: 0.5,
    ActionType.TALK_TO: 0.1,
    ActionType.WARMUP: 0.2,
    ActionType.TRAIN: 0.3,
    ActionType.CHANGE_STANCE: 0.1,
    ActionType.MOVE: 0.3,
    ActionType.CHANGE_STATUS: 0.1,
    ActionType.CREATE_SHELTER: 0.3,
    ActionType.ATTACK: 0.5,
    ActionType.GROW_FOOD: 0.5,
    ActionType.COOK_FOOD: 0.3,
    ActionType.STEAL: 0.2,
    ActionType.CREATE_STORAGE: 0.3,
    ActionType.GATHER_WOOD: 0.3,
    ActionType.PICK_RESOURCE: 0.1,
    ActionType.FISH: 0.3,
    ActionType.TRADE: 0.1,
}


ACTION_DESCRIPTIONS: dict[ActionType, str] = {
    ActionType.WAIT: "Do nothing and skip the turn.",
    ActionType.SLEEP: "Risk of getting robbed but improves mental health.",
    ActionType.EAT: "Consume food to reduce hunger.",
    ActionType.DRINK: "Consume water to reduce thirst.",
    ActionType.HEAL: "Consume light or heavy meds to restore health.",
    ActionType.TALK_TO: "Talked to another agent",
    ActionType.WARMUP: "Consume wood and fuel to create fire to improve warmth.",
    ActionType.TRAIN: "Increase strength.",
    ActionType.CHANGE_STANCE: "Switch between normal and sneak movement/visibility.",
    ActionType.MOVE: "Move to a visible tile.",
    ActionType.CHANGE_STATUS: "Switch between normal and guarding.",
    ActionType.CREATE_SHELTER: "Consume materials to create shelter on a tile.",
    ActionType.ATTACK: "Attack a visible agent.",
    ActionType.GROW_FOOD: "Plant seeds or materials on land; food appears in 3 iterations.",
    ActionType.COOK_FOOD: "Consume raw food and wood/fuel to make cooked food.",
    ActionType.STEAL: "Try to steal from a shelter tile, with a chance of getting caught.",
    ActionType.CREATE_STORAGE: "Consume wood to create storage on a shelter tile.",
    ActionType.GATHER_WOOD: "Gather wood from a forest tile; tools improve output.",
    ActionType.PICK_RESOURCE: "Pick a resource from the current tile.",
    ActionType.FISH: "Use a fishing rod on a water tile for a chance at raw food.",
    ActionType.TRADE: "Reserve budget to trade with a visible agent.",
}


ACTION_FIELD_SPECS: dict[ActionType, dict[str, Any]] = {
    ActionType.WAIT: {"required_fields": {}, "notes": "No fields required."},
    ActionType.SLEEP: {"required_fields": {}, "notes": "No fields required."},
    ActionType.TRAIN: {"required_fields": {}, "notes": "No fields required."},
    ActionType.EAT: {
        "required_fields": {"consumable": "Food resource name from your inventory."},
    },
    ActionType.DRINK: {
        "required_fields": {"consumable": "Water resource name from your inventory."},
    },
    ActionType.HEAL: {
        "required_fields": {"consumable": "Medication resource name from your inventory."},
    },
    ActionType.TALK_TO: {
        "required_fields": {"target": "Public key string of a visible agent."},
    },
    ActionType.WARMUP: {
        "required_fields": {"consumable": "fuel or wood from your inventory."},
    },
    ActionType.CHANGE_STANCE: {
        "required_fields": {"target": "Either normal or sneak."},
    },
    ActionType.MOVE: {
        "required_fields": {"target": {"x": "visible passable tile x", "y": "visible passable tile y"}},
    },
    ActionType.CHANGE_STATUS: {
        "required_fields": {"target": "Either normal or guarding."},
    },
    ActionType.CREATE_SHELTER: {
        "required_fields": {"target": {"x": "visible passable tile x", "y": "visible passable tile y"}},
    },
    ActionType.ATTACK: {
        "required_fields": {"target": {"id": "visible agent id", "public_key": "visible agent public key"}},
    },
    ActionType.GROW_FOOD: {
        "required_fields": {"target": {"x": "visible land tile x", "y": "visible land tile y"}},
    },
    ActionType.COOK_FOOD: {
        "required_fields": {
            "consumable": "raw_food",
            "item": "fuel or wood from your inventory",
        },
    },
    ActionType.STEAL: {
        "required_fields": {"target": {"x": "visible tile x with another agent shelter", "y": "visible tile y"}},
    },
    ActionType.CREATE_STORAGE: {
        "required_fields": {"target": {"x": "visible own shelter tile x", "y": "visible own shelter tile y"}},
    },
    ActionType.GATHER_WOOD: {
        "required_fields": {"target": {"x": "current forest tile x", "y": "current forest tile y"}},
    },
    ActionType.PICK_RESOURCE: {
        "required_fields": {"consumable": "Resource name present on your current tile."},
    },
    ActionType.FISH: {
        "required_fields": {"target": {"x": "visible water tile x", "y": "visible water tile y"}},
    },
    ActionType.TRADE: {
        "required_fields": {"target": {"id": "visible agent id", "public_key": "visible agent public key"}},
    },
}


FOOD_RESOURCES = (
    ResourceType.COOKED_FOOD,
    ResourceType.PROCESSED_FOOD,
    ResourceType.RAW_FOOD,
)
WATER_RESOURCES = (ResourceType.CLEAN_WATER, ResourceType.DIRTY_WATER)
MED_RESOURCES = (ResourceType.HEAVY_MEDS, ResourceType.LIGHT_MEDS)
WARMUP_RESOURCES = (ResourceType.FUEL, ResourceType.WOOD)
COOK_FUEL_RESOURCES = (ResourceType.FUEL, ResourceType.WOOD)
PASSABLE_TILE_TYPES = (TileType.LAND, TileType.FOREST, TileType.BUILDING)


@dataclass(frozen=True)
class Action:
    action_type: ActionType
    target: Any = None
    consumable: Any = None
    item: Any = None
    budget: float = 0.0
    description: str | None = None

    def __post_init__(self) -> None:
        action_type = ActionType(self.action_type)
        object.__setattr__(self, "action_type", action_type)
        object.__setattr__(self, "budget", ACTION_BUDGETS[action_type])
        if self.description is None:
            object.__setattr__(self, "description", ACTION_DESCRIPTIONS[action_type])

    @property
    def action(self) -> str:
        return self.action_type.value

    @classmethod
    def from_dict(cls, data: Any) -> "Action":
        if isinstance(data, Action):
            return data
        if isinstance(data, str):
            return cls(action_type=ActionType(data))
        if not isinstance(data, dict):
            raise ValueError("Action payload must be a string or object")

        action_value = data.get("action") or data.get("action_type") or data.get("type")
        if action_value is None:
            raise ValueError("Action payload missing action")

        return cls(
            action_type=ActionType(action_value),
            target=data.get("target"),
            consumable=data.get("consumable"),
            item=data.get("item"),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "action": self.action_type.value,
            "budget": self.budget,
            "description": self.description,
        }
        if self.target is not None:
            result["target"] = _json_value(self.target)
        if self.consumable is not None:
            result["consumable"] = _json_value(self.consumable)
        if self.item is not None:
            result["item"] = _json_value(self.item)
        return result


def valid_action(sim: "Simulation", agent: "Agent", action: Action | dict[str, Any] | str) -> bool:
    if not agent.alive:
        return False

    try:
        parsed_action = Action.from_dict(action)
    except (ValueError, TypeError):
        return False

    return any(
        _action_matches_template(parsed_action, valid_template)
        for valid_template in _create_valid_action_objects(sim, agent)
    )


def execute_action(sim: "Simulation", agent: "Agent", action: Action | dict[str, Any] | str) -> None:
    action = Action.from_dict(action)

    if action.action_type == ActionType.WAIT:
        return
    if action.action_type == ActionType.SLEEP:
        _sleep(sim, agent)
    elif action.action_type == ActionType.EAT:
        _eat(agent, action)
    elif action.action_type == ActionType.DRINK:
        _drink(agent, action)
    elif action.action_type == ActionType.HEAL:
        _heal(agent, action)
    elif action.action_type == ActionType.TALK_TO:
        return
    elif action.action_type == ActionType.WARMUP:
        _warmup(agent, action)
    elif action.action_type == ActionType.TRAIN:
        agent.strength += 2
    elif action.action_type == ActionType.CHANGE_STANCE:
        _change_stance(agent, action)
    elif action.action_type == ActionType.MOVE:
        _move(sim, agent, action)
    elif action.action_type == ActionType.CHANGE_STATUS:
        _change_status(agent, action)
    elif action.action_type == ActionType.CREATE_SHELTER:
        _create_shelter(sim, agent, action)
    elif action.action_type == ActionType.ATTACK:
        target_agent = _find_agent(sim, action.target)
        if target_agent is not None and target_agent is not agent:
            _apply_attack(sim, agent, target_agent)
    elif action.action_type == ActionType.GROW_FOOD:
        _grow_food(sim, agent, action)
    elif action.action_type == ActionType.COOK_FOOD:
        _cook_food(agent, action)
    elif action.action_type == ActionType.STEAL:
        _steal(sim, agent, action)
    elif action.action_type == ActionType.CREATE_STORAGE:
        _create_storage(sim, agent, action)
    elif action.action_type == ActionType.GATHER_WOOD:
        _gather_wood(sim, agent, action)
    elif action.action_type == ActionType.PICK_RESOURCE:
        _pick_resource(sim, agent, action)
    elif action.action_type == ActionType.FISH:
        _fish(sim, agent, action)
    elif action.action_type == ActionType.TRADE:
        return


def create_valid_actions(sim: "Simulation", agent: "Agent") -> list[dict[str, Any]]:
    action_types = []
    seen = set()
    for action in _create_valid_action_objects(sim, agent):
        if action.action_type in seen:
            continue
        seen.add(action.action_type)
        action_types.append(action.action_type)

    return [_action_spec(action_type) for action_type in action_types]


def _action_spec(action_type: ActionType) -> dict[str, Any]:
    field_spec = ACTION_FIELD_SPECS[action_type]
    result = {
        "action": action_type.value,
        "budget": ACTION_BUDGETS[action_type],
        "description": ACTION_DESCRIPTIONS[action_type],
        "required_fields": _json_value(field_spec["required_fields"]),
    }
    if "notes" in field_spec:
        result["notes"] = field_spec["notes"]
    return result


def _create_valid_action_objects(sim: "Simulation", agent: "Agent") -> list[Action]:
    if not agent.alive:
        return []

    actions = [
        Action(ActionType.WAIT),
        Action(ActionType.SLEEP),
        Action(ActionType.TRAIN),
    ]

    current_tile = _current_tile(sim, agent)

    _add_inventory_actions(actions, agent)
    _add_social_actions(actions, sim, agent)
    _add_stance_actions(actions, agent)
    _add_status_actions(actions, agent)
    _add_move_actions(actions, sim, agent)
    _add_tile_actions(actions, sim, agent, current_tile)

    return actions


def _add_inventory_actions(actions: list[Action], agent: "Agent") -> None:
    for resource in FOOD_RESOURCES:
        if _has_resource(agent, resource):
            actions.append(Action(ActionType.EAT, consumable=resource))

    for resource in WATER_RESOURCES:
        if _has_resource(agent, resource):
            actions.append(Action(ActionType.DRINK, consumable=resource))

    for resource in MED_RESOURCES:
        if _has_resource(agent, resource):
            actions.append(Action(ActionType.HEAL, consumable=resource))

    for resource in WARMUP_RESOURCES:
        if _has_resource(agent, resource):
            actions.append(Action(ActionType.WARMUP, consumable=resource))

    if _has_resource(agent, ResourceType.RAW_FOOD):
        for fuel in COOK_FUEL_RESOURCES:
            if _has_resource(agent, fuel):
                actions.append(
                    Action(
                        ActionType.COOK_FOOD,
                        consumable=ResourceType.RAW_FOOD,
                        item=fuel,
                    )
                )


def _add_social_actions(actions: list[Action], sim: "Simulation", agent: "Agent") -> None:
    for other_agent in sim.agents:
        if other_agent is agent or not other_agent.alive:
            continue
        if (other_agent.pos_x, other_agent.pos_y) not in agent.visible_tiles:
            continue

        target = _agent_target(other_agent)
        actions.append(Action(ActionType.TALK_TO, target=other_agent.public_key))
        actions.append(Action(ActionType.TRADE, target=target))
        actions.append(Action(ActionType.ATTACK, target=target))


def _add_stance_actions(actions: list[Action], agent: "Agent") -> None:
    current_stance = getattr(agent, "stance", "normal")
    for stance in ("normal", "sneak"):
        if stance != current_stance:
            actions.append(Action(ActionType.CHANGE_STANCE, target=stance))


def _add_status_actions(actions: list[Action], agent: "Agent") -> None:
    current_status = "guarding" if "guarding" in agent.status else "normal"
    for status in ("normal", "guarding"):
        if status != current_status:
            actions.append(Action(ActionType.CHANGE_STATUS, target=status))


def _add_move_actions(actions: list[Action], sim: "Simulation", agent: "Agent") -> None:
    move_radius = 1 if getattr(agent, "stance", "normal") == "sneak" else 3

    for x, y in agent.visible_tiles:
        if x == agent.pos_x and y == agent.pos_y:
            continue
        if max(abs(x - agent.pos_x), abs(y - agent.pos_y)) > move_radius:
            continue
        tile = sim.map.grid[y][x]
        if tile.type in PASSABLE_TILE_TYPES:
            actions.append(Action(ActionType.MOVE, target={"x": x, "y": y}))


def _add_tile_actions(actions: list[Action], sim: "Simulation", agent: "Agent", current_tile: Any) -> None:
    if current_tile.type == TileType.FOREST:
        actions.append(Action(ActionType.GATHER_WOOD, target=_tile_target(current_tile)))

    for resource, amount in current_tile.resources.items():
        if amount > 0:
            actions.append(Action(ActionType.PICK_RESOURCE, consumable=resource))

    if _has_resource(agent, ResourceType.MATERIALS):
        for x, y in agent.visible_tiles:
            tile = sim.map.grid[y][x]
            if tile.type in PASSABLE_TILE_TYPES:
                actions.append(Action(ActionType.CREATE_SHELTER, target={"x": x, "y": y}))

    if _has_resource(agent, ResourceType.SEEDS) or _has_resource(agent, ResourceType.MATERIALS):
        for x, y in agent.visible_tiles:
            tile = sim.map.grid[y][x]
            if tile.type == TileType.LAND:
                actions.append(Action(ActionType.GROW_FOOD, target={"x": x, "y": y}))

    if _has_resource(agent, ResourceType.WOOD):
        for x, y in agent.visible_tiles:
            tile = sim.map.grid[y][x]
            if agent.public_key in getattr(tile, "shelters", {}):
                actions.append(Action(ActionType.CREATE_STORAGE, target={"x": x, "y": y}))

    for x, y in agent.visible_tiles:
        tile = sim.map.grid[y][x]
        if tile.type == TileType.WATER and _has_resource(agent, ResourceType.FISHING_ROD):
            actions.append(Action(ActionType.FISH, target={"x": x, "y": y}))
        if any(owner != agent.public_key for owner in getattr(tile, "shelters", {})):
            actions.append(Action(ActionType.STEAL, target={"x": x, "y": y}))


def _action_matches_template(action: Action, template: Action) -> bool:
    if action.action_type != template.action_type:
        return False

    if not _field_matches(action.target, template.target):
        return False

    if not _field_matches(action.consumable, template.consumable):
        return False

    if action.action_type == ActionType.TRADE:
        return True

    return _field_matches(action.item, template.item)


def _field_matches(value: Any, template: Any) -> bool:
    if template is None:
        return value is None
    return _canonical_value(value) == _canonical_value(template)


def _sleep(sim: "Simulation", agent: "Agent") -> None:
    agent.mental_health = min(100, agent.mental_health + 15)

    current_tile = _current_tile(sim, agent)
    has_shelter = agent.public_key in getattr(current_tile, "shelters", {})
    if has_shelter or not agent.inventory or sim.rng.random() >= 0.2:
        return

    stealable = [resource for resource, amount in agent.inventory.items() if amount > 0]
    if not stealable:
        return

    stolen_resource = sim.rng.choice(stealable)
    agent.inventory[stolen_resource] -= 1


def _eat(agent: "Agent", action: Action) -> None:
    resource = _choose_resource(agent, action.consumable, FOOD_RESOURCES)
    if resource is None or not _consume_resource(agent, resource):
        return

    hunger_reduction = 20 if resource == ResourceType.RAW_FOOD else 30
    agent.hunger = max(0, agent.hunger - hunger_reduction)


def _drink(agent: "Agent", action: Action) -> None:
    resource = _choose_resource(agent, action.consumable, WATER_RESOURCES)
    if resource is None or not _consume_resource(agent, resource):
        return

    agent.thirst = max(0, agent.thirst - 35)
    if resource == ResourceType.DIRTY_WATER:
        agent.health -= 5


def _heal(agent: "Agent", action: Action) -> None:
    resource = _choose_resource(agent, action.consumable, MED_RESOURCES)
    if resource is None or not _consume_resource(agent, resource):
        return

    health_gain = 50 if resource == ResourceType.HEAVY_MEDS else 20
    agent.health = min(100, agent.health + health_gain)


def _warmup(agent: "Agent", action: Action) -> None:
    resource = _choose_resource(agent, action.consumable, WARMUP_RESOURCES)
    if resource is None or not _consume_resource(agent, resource):
        return

    warmth_gain = 30 if resource == ResourceType.FUEL else 20
    agent.warmth = min(100, agent.warmth + warmth_gain)


def _change_stance(agent: "Agent", action: Action) -> None:
    if action.target not in ("normal", "sneak"):
        return
    agent.stance = action.target
    agent.update_visible_tiles()


def _change_status(agent: "Agent", action: Action) -> None:
    if action.target == "guarding":
        if "guarding" not in agent.status:
            agent.status.append("guarding")
    elif action.target == "normal" and "guarding" in agent.status:
        agent.status.remove("guarding")


def _move(sim: "Simulation", agent: "Agent", action: Action) -> None:
    target = _target_xy(action.target)
    if target is None:
        return

    x, y = target
    old_tile = _current_tile(sim, agent)
    new_tile = sim.map.grid[y][x]

    if agent in old_tile.occupants:
        old_tile.occupants.remove(agent)

    for occupant in list(new_tile.occupants):
        if occupant is not agent and "guarding" in occupant.status and occupant.alive:
            _apply_attack(sim, occupant, agent)
            if not agent.alive:
                return

    new_tile.occupants.append(agent)
    agent.pos_x = x
    agent.pos_y = y
    agent.update_visible_tiles()


def _create_shelter(sim: "Simulation", agent: "Agent", action: Action) -> None:
    target = _target_xy(action.target) or (agent.pos_x, agent.pos_y)
    tile = sim.map.grid[target[1]][target[0]]
    if not _consume_resource(agent, ResourceType.MATERIALS):
        return
    tile.shelters[agent.public_key] = {"created_iteration": sim.iteration}


def _grow_food(sim: "Simulation", agent: "Agent", action: Action) -> None:
    target = _target_xy(action.target) or (agent.pos_x, agent.pos_y)
    tile = sim.map.grid[target[1]][target[0]]

    seed_resource = ResourceType.SEEDS if _has_resource(agent, ResourceType.SEEDS) else ResourceType.MATERIALS
    if not _consume_resource(agent, seed_resource):
        return

    tile.crops.append(
        {
            "owner": agent.public_key,
            "created_iteration": sim.iteration,
            "ready_iteration": sim.iteration + 3,
        }
    )


def _cook_food(agent: "Agent", action: Action) -> None:
    fuel = _choose_resource(agent, action.item, COOK_FUEL_RESOURCES)
    if fuel is None:
        return
    if not _consume_resource(agent, ResourceType.RAW_FOOD):
        return
    if not _consume_resource(agent, fuel):
        agent.inventory[ResourceType.RAW_FOOD] = agent.inventory.get(ResourceType.RAW_FOOD, 0) + 1
        return

    agent.inventory[ResourceType.COOKED_FOOD] = agent.inventory.get(ResourceType.COOKED_FOOD, 0) + 1


def _steal(sim: "Simulation", agent: "Agent", action: Action) -> None:
    target = _target_xy(action.target) or (agent.pos_x, agent.pos_y)
    tile = sim.map.grid[target[1]][target[0]]

    if sim.rng.random() < 0.35:
        for occupant in tile.occupants:
            if occupant is not agent and occupant.alive:
                _apply_attack(sim, occupant, agent)
                return
        agent.mental_health = max(0, agent.mental_health - 5)
        return

    for owner, storage in getattr(tile, "storages", {}).items():
        if owner == agent.public_key:
            continue
        for resource, amount in storage.items():
            if amount > 0:
                storage[resource] -= 1
                agent.inventory[resource] = agent.inventory.get(resource, 0) + 1
                return


def _create_storage(sim: "Simulation", agent: "Agent", action: Action) -> None:
    target = _target_xy(action.target) or (agent.pos_x, agent.pos_y)
    tile = sim.map.grid[target[1]][target[0]]

    if agent.public_key not in getattr(tile, "shelters", {}):
        return
    if not _consume_resource(agent, ResourceType.WOOD):
        return

    tile.storages.setdefault(agent.public_key, {resource: 0 for resource in ResourceType})


def _gather_wood(sim: "Simulation", agent: "Agent", action: Action) -> None:
    target = _target_xy(action.target) or (agent.pos_x, agent.pos_y)
    tile = sim.map.grid[target[1]][target[0]]
    if tile.type != TileType.FOREST:
        return

    amount = 5 if _has_resource(agent, ResourceType.TOOLS) else 1
    agent.inventory[ResourceType.WOOD] = agent.inventory.get(ResourceType.WOOD, 0) + amount


def _pick_resource(sim: "Simulation", agent: "Agent", action: Action) -> None:
    tile = _current_tile(sim, agent)
    resource = _resource_from_value(action.consumable) if action.consumable is not None else None

    if resource is not None:
        _move_tile_resource_to_inventory(tile, agent, resource)
        return

    for tile_resource in ResourceType:
        _move_tile_resource_to_inventory(tile, agent, tile_resource)


def _fish(sim: "Simulation", agent: "Agent", action: Action) -> None:
    if not _has_resource(agent, ResourceType.FISHING_ROD):
        return

    if sim.rng.random() < 0.7:
        agent.inventory[ResourceType.RAW_FOOD] = agent.inventory.get(ResourceType.RAW_FOOD, 0) + 1


def _apply_attack(sim: "Simulation", attacker: "Agent", defender: "Agent") -> None:
    damage = max(5, int((attacker.strength / 10) + sim.rng.randint(0, 12)))
    defender.health -= damage
    defender.mental_health = max(0, defender.mental_health - 5)

    if defender.health <= 0:
        defender.die()
        tile = sim.map.grid[defender.pos_y][defender.pos_x]
        if defender in tile.occupants:
            tile.occupants.remove(defender)


def _move_tile_resource_to_inventory(tile: Any, agent: "Agent", resource: ResourceType) -> None:
    amount = tile.resources.get(resource, 0)
    if amount <= 0:
        return
    tile.resources[resource] = 0
    agent.inventory[resource] = agent.inventory.get(resource, 0) + amount


def _consume_resource(agent: "Agent", resource: ResourceType, amount: int = 1) -> bool:
    if agent.inventory.get(resource, 0) < amount:
        return False
    agent.inventory[resource] -= amount
    return True


def _has_resource(agent: "Agent", resource: ResourceType, amount: int = 1) -> bool:
    return agent.inventory.get(resource, 0) >= amount


def _choose_resource(
    agent: "Agent",
    requested: Any,
    allowed_resources: tuple[ResourceType, ...],
) -> ResourceType | None:
    requested_resource = _resource_from_value(requested)
    if requested_resource is not None:
        if requested_resource in allowed_resources and _has_resource(agent, requested_resource):
            return requested_resource
        return None

    for resource in allowed_resources:
        if _has_resource(agent, resource):
            return resource
    return None


def _resource_from_value(value: Any) -> ResourceType | None:
    if value is None:
        return None
    if isinstance(value, ResourceType):
        return value
    try:
        return ResourceType(value)
    except (TypeError, ValueError):
        return None


def _current_tile(sim: "Simulation", agent: "Agent") -> Any:
    return sim.map.grid[agent.pos_y][agent.pos_x]


def _target_xy(target: Any) -> tuple[int, int] | None:
    if isinstance(target, dict) and "x" in target and "y" in target:
        return int(target["x"]), int(target["y"])
    if isinstance(target, (list, tuple)) and len(target) == 2:
        return int(target[0]), int(target[1])
    return None


def _find_agent(sim: "Simulation", target: Any) -> "Agent | None":
    for agent in sim.agents:
        if isinstance(target, dict):
            if target.get("id") == agent.id or target.get("public_key") == agent.public_key:
                return agent
        elif target == agent.id or target == agent.public_key:
            return agent
    return None


def _agent_target(agent: "Agent") -> dict[str, Any]:
    return {"id": agent.id, "public_key": agent.public_key}


def _tile_target(tile: Any) -> dict[str, int]:
    return {"x": tile.pos_x, "y": tile.pos_y}


def _canonical_value(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


def _json_value(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {key: _json_value(nested_value) for key, nested_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value
