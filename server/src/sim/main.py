from concurrent.futures import ThreadPoolExecutor
from .map import Map
from .agent import Agent
from .sim import Simulation
from uuid import uuid4
import logging


logger = logging.getLogger(__name__)

sim_executor = ThreadPoolExecutor()


def sim_done(future):
    if future.cancelled():
        return

    ex = future.exception()
    if ex is not None:
        logger.error("simulation crashed", exc_info=(type(ex), ex, ex.__traceback__))


def setup(agent_public_keys, seed):
    sim = create_simulation(agent_public_keys, seed)
    sim.future = sim_executor.submit(sim.run)
    sim.future.add_done_callback(sim_done)
    return sim


def create_simulation(agent_public_keys, seed):
    # generate map
    map = Map(seed)
    logger.info("creating simulation seed=%s agents=%s", seed, agent_public_keys)
    logger.info("initial resources\n%s", map.render_resources())

    # create agents
    agents = []
    for id, agent_key in enumerate(agent_public_keys):
        agent = Agent(id, agent_key) 
        agents.append(agent)

    # spawn agents
    map.add_agents(agents)
    logger.info("initial map\n%s", map.render())

    # run sim
    sim_id = uuid4().hex
    sim = Simulation(sim_id, map, agents, seed)
    logger.info("simulation created sim_id=%s seed=%s", sim_id, seed)
    return sim
