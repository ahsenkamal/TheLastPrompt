import argparse
from pathlib import Path

from common import axl
from common.logging_config import setup_logging
from . import config
from .sim import client_loop
import logging


logger = logging.getLogger(__name__)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt_path", type=Path, help="Path to prompt.txt")
    return parser.parse_args()

def send_matchmaking_request(self_public_key: str):
    message = {
        "protocol_version": config.PROTOCOL_VERSION,
        "message_type": config.MESSAGE_TYPE_MATCHMAKING_JOIN,
        "content": {
            "public_key": self_public_key,
        },
    }
    axl.send(message, config.SERVER_PUBLIC_KEY)
    logger.info("sent matchmaking request to server=%s", config.SERVER_PUBLIC_KEY)

def main():
    setup_logging("client")
    args = parse_args()
    config.USER_PROMPT = args.prompt_path.read_text(encoding="utf-8").strip()

    # wallet
    # ENS

    # setup axl
    self_public_key = axl.get_self_public_key()
    logger.info("client public_key=%s prompt_path=%s", self_public_key, args.prompt_path)

    # send matchmaking request to server
    send_matchmaking_request(self_public_key)

    client_loop(self_public_key)

if __name__ == "__main__":
    main()
