import asyncio
from concurrent.futures import ThreadPoolExecutor


sim_executor = ThreadPoolExecutor()


def sim_done(future):
    if future.cancelled():
        return

    ex = future.exception()
    if ex is not None:
        print(f"Simulation crashed: {ex}")


def setup(agents):
    loop = asyncio.get_running_loop()
    sim_future = loop.run_in_executor(sim_executor, start, agents)
    sim_future.add_done_callback(sim_done)
    return sim_future


def start(agents):
    # generate map
    # create agents
    # spawn agents
    # iterate ticks

    for tick in range(100):
        pass