from .types import *
from .grid import generate_grid, print_grid
from .agent import Agent
import random


class Tile:
    def __init__(self, pos_x, pos_y, tile_type):
        self.pos_x = pos_x
        self.pos_y = pos_y
        self.type = TileType(tile_type)
        self.occupants: list[Agent] = []
        self.resources = {resource_type: 0 for resource_type in ResourceType}


class Map:
    def __init__(self, seed):
        self.seed = seed
        self.rng = random.Random(seed)
        self.base_grid = generate_grid(seed)
        self.grid = [
            [Tile(x, y, tile_type) for x, tile_type in enumerate(row)]
            for y, row in enumerate(self.base_grid)
        ]
    
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