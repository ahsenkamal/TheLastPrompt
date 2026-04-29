import requests, json, time

AXL = "http://127.0.0.1:9002"

def get_self_public_key():
    resp = requests.get(f"{AXL}/topology")
    if resp.status_code == 200:
        topology = resp.json()
        return topology['our_public_key']

def send(message, peer_id):
    requests.post(f"{AXL}/send",
        headers={"X-Destination-Peer-Id": peer_id},
        data=json.dumps(message))

def recv_loop():
    while True:
        resp = requests.get(f"{AXL}/recv")
        if resp.status_code == 200:
            sender = resp.headers.get("X-From-Peer-Id")
            print(f"From {sender[:8]}...: {resp.text}")
        time.sleep(0.2)