from .types import ResourceType
from server.config import MAP_SIZE

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
        self.status: list[str] = []
        self.action_budget = 1.0
        self.actions: dict[int, list[str]] = {}
        self.valid_actions: dict[int, list[str]] = {}
        self.visible_tiles: list[tuple[int, int]] = []
        # self.memory

    def die(self):
        self.alive = False

    def update_visible_tiles(self):
        self.visible_tiles = [
            (x, y)
            for y in range(max(0, self.pos_y - 3), min(MAP_SIZE, self.pos_y + 4))
            for x in range(max(0, self.pos_x - 3), min(MAP_SIZE, self.pos_x + 4))
        ]
