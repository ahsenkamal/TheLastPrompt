from .types import ResourceType

class Agent:
    def __init__(self, id: str):
        self.id = id
        self.pos_x = 0
        self.pos_y = 0
        self.inventory: dict[ResourceType, int]= {}
        self.inventory_weight = 0
        self.health = 100
        self.hunger = 0
        self.thirst = 0
        self.stamina = 100
        self.mental_health = 100
        self.warmth = 100
        self.reputation = 0
        self.alive = True
        self.strength = 33
        self.status: list[str] = []