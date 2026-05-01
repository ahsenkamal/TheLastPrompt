import json
import os

import requests

AXL = os.getenv("AXL_BASE_URL", "http://127.0.0.1:9002")
AXL_TIMEOUT_SECONDS = float(os.getenv("AXL_TIMEOUT_SECONDS", "30"))


def get_self_public_key():
    resp = requests.get(f"{AXL}/topology", timeout=AXL_TIMEOUT_SECONDS)
    if resp.status_code == 200:
        topology = resp.json()
        return topology['our_public_key']
    else:
        raise Exception("AXL not set up correctly or not running")


def send(message, peer_id):
    resp = requests.post(
        f"{AXL}/send",
        headers={"X-Destination-Peer-Id": peer_id},
        data=json.dumps(message),
        timeout=AXL_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()


def recv():
    try:
        resp = requests.get(f"{AXL}/recv", timeout=AXL_TIMEOUT_SECONDS)
    except requests.Timeout:
        return None
    if resp.status_code == 204:
        return None
    resp.raise_for_status()
    if resp.status_code == 200:
        sender = resp.headers.get("X-From-Peer-Id")
        if sender is None:
            return None
        return (sender, resp.text)
    return None
