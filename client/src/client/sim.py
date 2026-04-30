from . import config
from common import axl
import time
import json
from .state import State

def client_loop():
    state: State = None

    while True:
        # wait for state update from server
        received = axl.recv()
        if received is None:
            time.sleep(0.1)
            continue

        sender, msg = received
        msg = json.loads(msg)

        if msg.get("protocol_version") != config.PROTOCOL_VERSION:
            print(f"Received message with unsupported protocol version: {msg.get('protocol_version')}")
            continue

        if sender != config.SERVER_PUBLIC_KEY:
            print(f"Received message from unknown sender: {sender}")
            continue
        
        if msg.get("message_type") != "STATE_UPDATE":
            print(f"Received message with unknown type: {msg.get('message_type')}")
            continue

        # update client state
        received_state = msg.get("content")

        if state is None:
            state = State(received_state)
        else:
            state.update(received_state)

        # create prompt for user and get response
        final_prompt = config.BASE_PROMPT + "\n\n" + config.USER_PROMPT + "\n\n" + state.get_state_description()
        print(final_prompt)

        # send response to server
        pass
