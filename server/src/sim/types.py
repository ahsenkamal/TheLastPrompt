from enum import StrEnum
from dataclasses import dataclass


class TileType(StrEnum):
    LAND = "land"
    WATER = "water"
    FOREST = "forest"
    MOUNTAIN = "mountain"
    BUILDING = "building"


class ResourceType(StrEnum):
    RAW_FOOD = "raw_food"
    COOKED_FOOD = "cooked_food"
    PROCESSED_FOOD = "processed_food"
    DIRTY_WATER = "dirty_water"
    CLEAN_WATER = "clean_water"
    LIGHT_MEDS = "light_meds"
    HEAVY_MEDS = "heavy_meds"
    MATERIALS = "materials"
    WOOD = "wood"
    SCRAP = "scrap"
    TOOLS = "tools"
    WEAPON_KNIFE = "knife"
    WEAPON_BOW = "bow"
    WEAPON_GUN = "gun"
    AMMO = "ammo"
    POWER_SOURCE = "power_source"
    MAP = "map"
    SATELLITE_TRACKER = "satellite_tracker"
    BINOCULARS = "binoculars"
    SEEDS = "seeds"
    FUEL = "fuel"
    BANDAGE = "bandage"
    FISHING_ROD = "fishing_rod"
    TRAP = "trap"
    CLOTHING = "clothing"
    BACKPACK = "backpack"