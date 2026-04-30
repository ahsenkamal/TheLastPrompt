from dataclasses import dataclass
from typing import Any
from .types import *
from .grid import generate_grid, print_grid
from .agent import Agent
import random


@dataclass(frozen=True)
class ResourceSpawnRule:
    resource: ResourceType
    chance: float
    min_amount: int
    max_amount: int


RESOURCE_SPAWN_RULES: dict[TileType, tuple[ResourceSpawnRule, ...]] = {
    TileType.LAND: (
        ResourceSpawnRule(ResourceType.RAW_FOOD, 0.30, 1, 3),
        ResourceSpawnRule(ResourceType.SEEDS, 0.35, 1, 2),
        ResourceSpawnRule(ResourceType.MATERIALS, 0.20, 1, 2),
        ResourceSpawnRule(ResourceType.DIRTY_WATER, 0.15, 1, 2),
    ),
    TileType.WATER: (
        ResourceSpawnRule(ResourceType.DIRTY_WATER, 0.90, 2, 5),
        ResourceSpawnRule(ResourceType.CLEAN_WATER, 0.20, 1, 2),
        ResourceSpawnRule(ResourceType.RAW_FOOD, 0.25, 1, 2),
    ),
    TileType.FOREST: (
        ResourceSpawnRule(ResourceType.WOOD, 0.80, 2, 6),
        ResourceSpawnRule(ResourceType.RAW_FOOD, 0.30, 1, 3),
        ResourceSpawnRule(ResourceType.SEEDS, 0.30, 1, 2),
        ResourceSpawnRule(ResourceType.MATERIALS, 0.20, 1, 2),
        ResourceSpawnRule(ResourceType.DIRTY_WATER, 0.10, 1, 2),
    ),
    TileType.MOUNTAIN: (
        ResourceSpawnRule(ResourceType.SCRAP, 0.35, 1, 3),
        ResourceSpawnRule(ResourceType.MATERIALS, 0.25, 1, 2),
        ResourceSpawnRule(ResourceType.POWER_SOURCE, 0.05, 1, 1),
    ),
    TileType.BUILDING: (
        ResourceSpawnRule(ResourceType.PROCESSED_FOOD, 0.45, 1, 3),
        ResourceSpawnRule(ResourceType.CLEAN_WATER, 0.35, 1, 3),
        ResourceSpawnRule(ResourceType.LIGHT_MEDS, 0.20, 1, 2),
        ResourceSpawnRule(ResourceType.HEAVY_MEDS, 0.08, 1, 1),
        ResourceSpawnRule(ResourceType.MATERIALS, 0.45, 1, 4),
        ResourceSpawnRule(ResourceType.SCRAP, 0.50, 1, 4),
        ResourceSpawnRule(ResourceType.TOOLS, 0.15, 1, 1),
        ResourceSpawnRule(ResourceType.FUEL, 0.18, 1, 2),
        ResourceSpawnRule(ResourceType.CLOTHING, 0.12, 1, 1),
        ResourceSpawnRule(ResourceType.BACKPACK, 0.08, 1, 1),
        ResourceSpawnRule(ResourceType.BANDAGE, 0.18, 1, 2),
        ResourceSpawnRule(ResourceType.FISHING_ROD, 0.08, 1, 1),
        ResourceSpawnRule(ResourceType.TRAP, 0.08, 1, 1),
        ResourceSpawnRule(ResourceType.MAP, 0.05, 1, 1),
        ResourceSpawnRule(ResourceType.BINOCULARS, 0.05, 1, 1),
        ResourceSpawnRule(ResourceType.WEAPON_KNIFE, 0.10, 1, 1),
        ResourceSpawnRule(ResourceType.WEAPON_BOW, 0.06, 1, 1),
        ResourceSpawnRule(ResourceType.WEAPON_GUN, 0.03, 1, 1),
        ResourceSpawnRule(ResourceType.AMMO, 0.10, 1, 4),
    ),
}


class Tile:
    def __init__(self, pos_x, pos_y, tile_type):
        self.pos_x = pos_x
        self.pos_y = pos_y
        self.type = TileType(tile_type)
        self.occupants: list[Agent] = []
        self.resources = {resource_type: 0 for resource_type in ResourceType}
        self.shelters: dict[str, dict] = {}
        self.storages: dict[str, dict[ResourceType, int]] = {}
        self.crops: list[dict] = []


class Map:
    def __init__(self, seed):
        self.seed = seed
        self.rng = random.Random(seed)
        self.resource_rng = random.Random((seed + 1) * 1_000_003)
        self.base_grid = generate_grid(seed)
        self.grid = [
            [Tile(x, y, tile_type) for x, tile_type in enumerate(row)]
            for y, row in enumerate(self.base_grid)
        ]
        self.spawn_resources()

    def print_base_grid(self):
        print_grid(self.base_grid)

    def print(self):
        for row in self.grid:
            for tile in row:
                print(tile.type.value[0].upper(), end="")
                if tile.occupants:
                    print("*", end=" ")
                else:
                    print(" ", end=" ")
            print()

    def render(self) -> str:
        lines = []
        for row in self.grid:
            cells = []
            for tile in row:
                occupants = ",".join(str(agent.id) for agent in tile.occupants if agent.alive)
                marker = occupants if occupants else "."
                cells.append(f"{tile.type.value[0].upper()}{marker}".ljust(5))
            lines.append(" ".join(cells).rstrip())
        return "\n".join(lines)

    def render_resources(self) -> str:
        lines = []
        for row in self.grid:
            for tile in row:
                resources = _positive_amounts(tile.resources)
                if resources:
                    lines.append(f"({tile.pos_x},{tile.pos_y}) {tile.type.value}: {resources}")
        return "\n".join(lines) if lines else "no resources"

    def spawn_resources(self):
        for row in self.grid:
            for tile in row:
                self.spawn_tile_resources(tile)

    def spawn_tile_resources(self, tile: Tile):
        for rule in RESOURCE_SPAWN_RULES.get(tile.type, ()):
            if self.resource_rng.random() <= rule.chance:
                tile.resources[rule.resource] += self.resource_rng.randint(rule.min_amount, rule.max_amount)

    def add_agents(self, agents):
        candidate_tiles = [
            (x, y)
            for y, row in enumerate(self.grid)
            for x, tile in enumerate(row)
            if tile.type not in (TileType.WATER, TileType.MOUNTAIN)
        ]

        if len(candidate_tiles) < len(agents):
            raise Exception("Not enough valid tiles to spawn agent")

        positions = self.rng.sample(candidate_tiles, len(agents))
        for agent, (x, y) in zip(agents, positions):
            tile = self.grid[y][x]
            tile.occupants.append(agent)
            agent.pos_x = x
            agent.pos_y = y
            agent.update_visible_tiles()


def _positive_amounts(values: dict[Any, int]) -> dict[str, int]:
    return {
        str(resource): amount
        for resource, amount in values.items()
        if amount > 0
    }
