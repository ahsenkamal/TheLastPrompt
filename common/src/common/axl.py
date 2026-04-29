import requests, json, time

AXL = "http://127.0.0.1:9002"

def get_self_public_key():
    resp = requests.get(f"{AXL}/topology")
    if resp.status_code == 200:
        topology = resp.json()
        return topology['our_public_key']
    else:
        raise Exception("AXL not set up correctly or not running")

def send(message, peer_id):
    requests.post(f"{AXL}/send",
        headers={"X-Destination-Peer-Id": peer_id},
        data=json.dumps(message))

def recv():
    resp = requests.get(f"{AXL}/recv")
    if resp.status_code == 200:
        sender = resp.headers.get("X-From-Peer-Id")
        if sender is None:
            return None
        return (sender, resp.text)