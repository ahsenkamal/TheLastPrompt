import json, asyncio
from common import axl
import sim
from .state import State
from .config import MAP_SIZE


async def handle_message(sender, msg, state: State):
    msg = json.loads(msg)
    if msg['type'] == 'MATCHMAKING_JOIN':
        state.add_to_queue(sender)
        if state.queue_ready():
            print("Matchmaking queue is ready, creating new game instance")
            agents = state.pick_new_sim_agents()
            state.sim_instances.append(sim.setup(agents, MAP_SIZE))


async def recv_loop(state: State):
    while True:
        received = axl.recv()
        if received is None:
            await asyncio.sleep(0.1)
            continue

        sender, msg = received
        await handle_message(sender, msg, state)
