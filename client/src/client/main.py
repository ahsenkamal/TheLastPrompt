import argparse
import logging
from pathlib import Path

from common import axl
from common.logging_config import demo_log, setup_logging
from . import config
from .dashboard import dashboard_url, start_dashboard
from .sim import client_loop


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

    # setup axl
    self_public_key = axl.get_self_public_key()
    logger.info("client public_key=%s prompt_path=%s", self_public_key, args.prompt_path)
    runtime = None
    profile = None
    if config.CLIENT_WALLET_LOGIN_REQUIRED and not config.CLIENT_DASHBOARD_ENABLED:
        raise SystemExit("CLIENT_DASHBOARD_ENABLED must be true when CLIENT_WALLET_LOGIN_REQUIRED=true")

    if config.CLIENT_DASHBOARD_ENABLED:
        runtime = start_dashboard(
            self_public_key,
            host=config.CLIENT_DASHBOARD_HOST,
            port=config.CLIENT_DASHBOARD_PORT,
            db_path=config.CLIENT_REPLAY_DB_PATH,
        )
        url = dashboard_url(config.CLIENT_DASHBOARD_HOST, config.CLIENT_DASHBOARD_PORT)
        if config.CLIENT_WALLET_LOGIN_REQUIRED:
            profile = _wait_for_ens_login(runtime, url)
        elif config.CLIENT_WALLET_LOGIN_WAIT_SECONDS > 0:
            logger.info(
                "waiting up to %.1fs for MetaMask profile on client dashboard",
                config.CLIENT_WALLET_LOGIN_WAIT_SECONDS,
            )
            profile = runtime.wait_for_profile(config.CLIENT_WALLET_LOGIN_WAIT_SECONDS)

    # send matchmaking request to server
    send_matchmaking_request(self_public_key, profile or (runtime.get_profile() if runtime is not None else None))

    client_loop(self_public_key, runtime)


def _wait_for_ens_login(runtime, url: str) -> dict:
    timeout = config.CLIENT_WALLET_LOGIN_WAIT_SECONDS
    timeout_text = "without a timeout" if timeout <= 0 else f"for up to {timeout:.1f}s"
    logger.info("MetaMask ENS login required before matchmaking; click %s", url)
    demo_log(logger, "MetaMask ENS login required before matchmaking: %s", url)
    logger.info("waiting %s for an ENS-backed wallet profile", timeout_text)
    profile = runtime.wait_for_profile(timeout, require_ens=True)
    ens_name = profile.get("ens_name")
    if not ens_name:
        message = (
            "ENS login is required before matchmaking. "
            f"Complete MetaMask login at {url}, then retry or increase CLIENT_WALLET_LOGIN_WAIT_SECONDS."
        )
        logger.error(message)
        raise SystemExit(message)
    logger.info("MetaMask ENS login complete ens_name=%s", ens_name)
    demo_log(logger, "Logged in as %s; joining matchmaking", ens_name)
    return profile


if __name__ == "__main__":
    main()
