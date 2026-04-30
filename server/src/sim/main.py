import asyncio
from concurrent.futures import ProcessPoolExecutor
from .map import Map
from .agent import Agent

sim_executor = ProcessPoolExecutor()


def sim_done(future):
    if future.cancelled():
        return

    ex = future.exception()
    if ex is not None:
        print(f"Simulation crashed: {ex}")


def setup(agents, seed):
    loop = asyncio.get_running_loop()
    sim_future = loop.run_in_executor(sim_executor, start, agents, seed)
    sim_future.add_done_callback(sim_done)
    return sim_future


def start(agent_ids, seed):
    # generate map
    map = Map(seed)
    map.print_base_grid()

    # create agents
    agents = []
    for agent_id in agent_ids:
        agent = Agent(agent_id) 
        agents.append(agent)

    # spawn agents
    map.add_agents(agents)
    map.print()

    # iterate ticks
    for tick in range(100):
        pass