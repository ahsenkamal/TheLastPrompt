from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING

from .types import ResourceType
from server.config import MAP_SIZE, NORMAL_VISIBILITY_RADIUS, SNEAK_VISIBILITY_RADIUS

if TYPE_CHECKING:
    from .action import Action


class Agent:
    def __init__(self, id, public_key: str):
        self.public_key = public_key
        self.id = id
        self.pos_x = 0
        self.pos_y = 0
        self.inventory: dict[ResourceType, int]= {}
        self.inventory_weight = 0
        self.health = 100
        self.hunger = 0
        self.thirst = 0
        self.mental_health = 100
        self.warmth = 100
        # self.reputation = 0
        self.alive = True
        self.strength = 33
        self.stance = "normal"
        self.status: list[str] = []
        self.action_budget = 1.0
        self.actions: dict[int, list[Action]] = {}
        self.actions_lock = Lock()
        self.visible_tiles: list[tuple[int, int]] = []
        self.death_tick: int | None = None
        self.death_cause: str | None = None
        self.killed_by: int | None = None
        # self.memory

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

    def queue_action(self, iteration: int, action: Action):
        with self.actions_lock:
            self.actions.setdefault(iteration, []).append(action)

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
