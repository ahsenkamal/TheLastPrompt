import argparse
from pathlib import Path

from common import axl
from common.logging_config import setup_logging
from . import config
from .dashboard import start_dashboard
from .sim import client_loop
import logging


logger = logging.getLogger(__name__)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt_path", type=Path, help="Path to prompt.txt")
    return parser.parse_args()

def send_matchmaking_request(self_public_key: str, agent_profile: dict | None = None):
    message = {
        "protocol_version": config.PROTOCOL_VERSION,
        "message_type": config.MESSAGE_TYPE_MATCHMAKING_JOIN,
        "content": {
            "public_key": self_public_key,
            "agent_profile": agent_profile or {},
        },
    }
    axl.send(message, config.SERVER_PUBLIC_KEY)
    logger.info(
        "sent matchmaking request to server=%s agent_name=%s",
        config.SERVER_PUBLIC_KEY,
        (agent_profile or {}).get("ens_name"),
    )

def main():
    setup_logging("client")
    args = parse_args()
    config.USER_PROMPT = args.prompt_path.read_text(encoding="utf-8").strip()

    # wallet
    # ENS

    # setup axl
    self_public_key = axl.get_self_public_key()
    logger.info("client public_key=%s prompt_path=%s", self_public_key, args.prompt_path)
    runtime = None
    if config.CLIENT_DASHBOARD_ENABLED:
        runtime = start_dashboard(
            self_public_key,
            host=config.CLIENT_DASHBOARD_HOST,
            port=config.CLIENT_DASHBOARD_PORT,
            db_path=config.CLIENT_REPLAY_DB_PATH,
        )
        if config.CLIENT_WALLET_LOGIN_WAIT_SECONDS > 0:
            logger.info(
                "waiting up to %.1fs for MetaMask profile on client dashboard",
                config.CLIENT_WALLET_LOGIN_WAIT_SECONDS,
            )
            runtime.wait_for_profile(config.CLIENT_WALLET_LOGIN_WAIT_SECONDS)

    # send matchmaking request to server
    send_matchmaking_request(self_public_key, runtime.get_profile() if runtime is not None else None)

    client_loop(self_public_key, runtime)

if __name__ == "__main__":
    main()
