import argparse
from pathlib import Path

from common import axl
from . import config
from .sim import client_loop

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt_path", type=Path, help="Path to prompt.txt")
    return parser.parse_args()

def send_matchmaking_request():
    message = {
        "protocol_version": config.PROTOCOL_VERSION,
        "message_type": config.MESSAGE_TYPE_MATCHMAKING_JOIN,
    }
    axl.send(message, config.SERVER_PUBLIC_KEY)

def main():
    args = parse_args()
    config.USER_PROMPT = args.prompt_path.read_text(encoding="utf-8").strip()

    # wallet
    # ENS

    # setup axl
    self_public_key = axl.get_self_public_key()

    # send matchmaking request to server
    send_matchmaking_request()

    client_loop(self_public_key)

if __name__ == "__main__":
    main()
