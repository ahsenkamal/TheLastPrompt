import asyncio
from concurrent.futures import ProcessPoolExecutor
from .map import Map
from .agent import Agent
from .sim import Simulation
from uuid import uuid4

sim_executor = ProcessPoolExecutor()


def sim_done(future):
    if future.cancelled():
        return

    ex = future.exception()
    if ex is not None:
        print(f"Simulation crashed: {ex}")


def setup(agent_public_keys, seed):
    loop = asyncio.get_running_loop()
    sim_future = loop.run_in_executor(sim_executor, start, agent_public_keys, seed)
    sim_future.add_done_callback(sim_done)
    return sim_future


def start(agent_public_keys, seed):
    # generate map
    map = Map(seed)
    map.print_base_grid()

    # create agents
    agents = []
    for id, agent_key in enumerate(agent_public_keys):
        agent = Agent(id, agent_key) 
        agents.append(agent)

    # spawn agents
    map.add_agents(agents)
    map.print()

    # run sim
    sim_id = uuid4().hex
    sim = Simulation(sim_id, map, agents, seed)
    sim.run()