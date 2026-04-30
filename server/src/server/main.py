from common import axl
from common.logging_config import setup_logging
from .state import State
from .messaging import recv_loop
from .config import *
import asyncio
import logging


logger = logging.getLogger(__name__)


async def run_server(): 
    # check axl
    self_public_key = axl.get_self_public_key()
    logger.info("server public_key=%s sim_size=%s", self_public_key, AGENTS_IN_SIM)

    # setup server state
    state = State(AGENTS_IN_SIM, self_public_key)

    await recv_loop(state)


def main():
    setup_logging("server")
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("server stopped")


if __name__ == "__main__":
    main()
