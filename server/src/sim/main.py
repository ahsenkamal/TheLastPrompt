from concurrent.futures import ThreadPoolExecutor
from .map import Map
from .agent import Agent
from .sim import Simulation
from uuid import uuid4

sim_executor = ThreadPoolExecutor()


def sim_done(future):
    if future.cancelled():
        return

    ex = future.exception()
    if ex is not None:
        print(f"Simulation crashed: {ex}")


def setup(agent_public_keys, seed):
    sim = create_simulation(agent_public_keys, seed)
    sim.future = sim_executor.submit(sim.run)
    sim.future.add_done_callback(sim_done)
    return sim


def create_simulation(agent_public_keys, seed):
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
    return sim
