from common import axl
from .state import State
from .messaging import recv_loop
from .config import *
import asyncio


async def run_server(): 
    # check axl
    self_public_key = axl.get_self_public_key()

    # setup server state
    state = State(AGENTS_IN_SIM, self_public_key)

    await recv_loop(state)


def main():
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
