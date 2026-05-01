from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING

from .types import ResourceType
from server.config import MAP_SIZE, NORMAL_VISIBILITY_RADIUS, SNEAK_VISIBILITY_RADIUS

if TYPE_CHECKING:
    from .action import Action


RESOURCE_WEIGHTS: dict[ResourceType, float] = {
    ResourceType.RAW_FOOD: 0.7,
    ResourceType.COOKED_FOOD: 0.6,
    ResourceType.PROCESSED_FOOD: 0.45,
    ResourceType.DIRTY_WATER: 1.0,
    ResourceType.CLEAN_WATER: 1.0,
    ResourceType.LIGHT_MEDS: 0.2,
    ResourceType.HEAVY_MEDS: 0.5,
    ResourceType.MATERIALS: 0.7,
    ResourceType.WOOD: 1.0,
    ResourceType.SCRAP: 1.1,
    ResourceType.TOOLS: 1.8,
    ResourceType.WEAPON_KNIFE: 0.4,
    ResourceType.WEAPON_BOW: 0.8,
    ResourceType.WEAPON_GUN: 1.5,
    ResourceType.AMMO: 0.05,
    ResourceType.POWER_SOURCE: 2.0,
    ResourceType.MAP: 0.1,
    ResourceType.BINOCULARS: 0.5,
    ResourceType.SEEDS: 0.05,
    ResourceType.FUEL: 0.8,
    ResourceType.BANDAGE: 0.1,
    ResourceType.FISHING_ROD: 0.6,
    ResourceType.TRAP: 1.2,
    ResourceType.CLOTHING: 1.0,
    ResourceType.BACKPACK: 0.8,
}

BASE_CARRY_CAPACITY = 12.0
BACKPACK_CARRY_BONUS = 8.0


class Agent:
    def __init__(self, id, public_key: str):
        self.public_key = public_key
        self.id = id
        self.pos_x = 0
        self.pos_y = 0
        self.inventory: dict[ResourceType, int] = {}
        self.inventory_weight = 0.0
        self.carry_capacity = BASE_CARRY_CAPACITY
        self.health = 100
        self.hunger = 0
        self.thirst = 0
        self.mental_health = 100
        self.warmth = 100
        self.reputation = 50.0
        self.trust: dict[int, float] = {}
        self.grudges: dict[int, float] = {}
        self.alive = True
        self.strength = 33
        self.stance = "normal"
        self.status: list[str] = []
        self.status_since: dict[str, int] = {}
        self.action_budget = 1.0
        self.actions: dict[int, list[Action]] = {}
        self.actions_lock = Lock()
        self.visible_tiles: list[tuple[int, int]] = []
        self.death_tick: int | None = None
        self.death_cause: str | None = None
        self.killed_by: int | None = None

    def die(self):
        self.alive = False
        self.health = 0
        self.action_budget = 0

    def clamp_metrics(self):
        self.health = _clamp(self.health)
        self.hunger = _clamp(self.hunger)
        self.thirst = _clamp(self.thirst)
        self.mental_health = _clamp(self.mental_health)
        self.warmth = _clamp(self.warmth)
        self.reputation = _clamp(self.reputation)
        self.status = list(dict.fromkeys(self.status))
        for status in list(self.status_since):
            if status not in self.status:
                self.status_since.pop(status, None)
        for relation in (self.trust, self.grudges):
            for agent_id, value in list(relation.items()):
                relation[agent_id] = _clamp(value)

    def add_status(self, status: str, iteration: int | None = None):
        if status not in self.status:
            self.status.append(status)
        if iteration is not None:
            self.status_since.setdefault(status, iteration)

    def remove_status(self, status: str):
        self.status = [item for item in self.status if item != status]
        self.status_since.pop(status, None)

    def status_age(self, status: str, iteration: int) -> int:
        started = self.status_since.get(status)
        if started is None:
            return 0
        return max(0, iteration - started)

    def recalculate_inventory(self):
        capacity = BASE_CARRY_CAPACITY
        if self.inventory.get(ResourceType.BACKPACK, 0) > 0:
            capacity += BACKPACK_CARRY_BONUS
        self.carry_capacity = capacity
        self.inventory_weight = round(
            sum(
                RESOURCE_WEIGHTS.get(resource, 0.5) * amount
                for resource, amount in self.inventory.items()
                if amount > 0
            ),
            2,
        )

    def remaining_capacity_for(self, resource: ResourceType) -> int:
        self.recalculate_inventory()
        weight = RESOURCE_WEIGHTS.get(resource, 0.5)
        if weight <= 0:
            return 100
        remaining = self.carry_capacity - self.inventory_weight
        return max(0, int(remaining // weight))

    def queue_action(self, iteration: int, action: Action):
        self.queue_actions(iteration, [action])

    def queue_actions(self, iteration: int, actions: list[Action]):
        with self.actions_lock:
            self.actions.setdefault(iteration, []).extend(actions)

    def pop_actions(self, iteration: int) -> list[Action]:
        with self.actions_lock:
            return self.actions.pop(iteration, [])

    def update_visible_tiles(self):
        radius = SNEAK_VISIBILITY_RADIUS if self.stance == "sneak" else NORMAL_VISIBILITY_RADIUS
        self.visible_tiles = [
            (x, y)
            for y in range(max(0, self.pos_y - radius), min(MAP_SIZE, self.pos_y + radius + 1))
            for x in range(max(0, self.pos_x - radius), min(MAP_SIZE, self.pos_x + radius + 1))
        ]


def _clamp(value: float, minimum: float = 0, maximum: float = 100) -> float:
    return max(minimum, min(maximum, value))
