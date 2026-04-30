from __future__ import annotations

import math
import random
from dataclasses import dataclass
from server.config import *


REGION_RANGES = (
    (0.20, "water"),
    (0.30, "building"),
    (0.50, "land"),
    (0.80, "forest"),
    (1.00, "mountain"),
)


@dataclass(frozen=True)
class NoiseLayer:
    scale: float
    offset_x: float
    offset_y: float
    weight: float


class PerlinNoise:
    def __init__(self, seed: int) -> None:
        rng = random.Random(seed)
        self._permutation = list(range(256))
        rng.shuffle(self._permutation)
        self._permutation *= 2

    def noise(self, x: float, y: float) -> float:
        x_cell = math.floor(x) & 255
        y_cell = math.floor(y) & 255
        x -= math.floor(x)
        y -= math.floor(y)

        u = self._fade(x)
        v = self._fade(y)

        top_left = self._permutation[self._permutation[x_cell] + y_cell]
        top_right = self._permutation[self._permutation[x_cell + 1] + y_cell]
        bottom_left = self._permutation[self._permutation[x_cell] + y_cell + 1]
        bottom_right = self._permutation[self._permutation[x_cell + 1] + y_cell + 1]

        top = self._lerp(
            self._gradient(top_left, x, y),
            self._gradient(top_right, x - 1, y),
            u,
        )
        bottom = self._lerp(
            self._gradient(bottom_left, x, y - 1),
            self._gradient(bottom_right, x - 1, y - 1),
            u,
        )

        return (self._lerp(top, bottom, v) + 1) / 2

    @staticmethod
    def _fade(value: float) -> float:
        return value * value * value * (value * (value * 6 - 15) + 10)

    @staticmethod
    def _lerp(start: float, end: float, amount: float) -> float:
        return start + amount * (end - start)

    @staticmethod
    def _gradient(hash_value: int, x: float, y: float) -> float:
        directions = ((1, 1), (-1, 1), (1, -1), (-1, -1), (1, 0), (-1, 0), (0, 1), (0, -1))
        gx, gy = directions[hash_value & 7]
        return gx * x + gy * y


def make_layers(rng: random.Random, base_scale: float) -> list[NoiseLayer]:
    layers = []
    for pass_index in range(NOISE_PASSES):
        frequency = 2**pass_index
        layers.append(
            NoiseLayer(
                scale=base_scale / frequency,
                offset_x=rng.uniform(-1000, 1000),
                offset_y=rng.uniform(-1000, 1000),
                weight=1 / frequency,
            )
        )
    return layers


def layered_noise(noise: PerlinNoise, x: int, y: int, layers: list[NoiseLayer]) -> float:
    total = 0.0
    total_weight = 0.0

    for layer in layers:
        sample_x = (x + layer.offset_x) / layer.scale
        sample_y = (y + layer.offset_y) / layer.scale
        total += noise.noise(sample_x, sample_y) * layer.weight
        total_weight += layer.weight

    return total / total_weight


def normalize_grid(values: list[list[float]]) -> list[list[float]]:
    flat_values = [value for row in values for value in row]
    lowest = min(flat_values)
    highest = max(flat_values)

    if lowest == highest:
        return [[0.0 for _ in row] for row in values]

    return [[(value - lowest) / (highest - lowest) for value in row] for row in values]


def classify_tile(value: float) -> str:
    for upper_limit, tile in REGION_RANGES:
        if value <= upper_limit:
            return tile
    return REGION_RANGES[-1][1]


def generate_grid(seed: int) -> list[list[str]]:
    noise = PerlinNoise(seed)
    rng = random.Random(seed)
    layers = make_layers(rng, base_scale=4.0)

    values = []
    for y in range(MAP_SIZE):
        row = []
        for x in range(MAP_SIZE):
            row.append(layered_noise(noise, x, y, layers))
        values.append(row)

    return [[classify_tile(value) for value in row] for row in normalize_grid(values)]


def print_grid(grid: list[list[str]]) -> None:
    print()
    for row in grid:
        for tile in row:
            print(tile[0].upper(), end=" ")
        print()
