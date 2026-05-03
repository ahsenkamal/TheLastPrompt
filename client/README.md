# The Last Prompt Client

LLM-powered agent runtime for The Last Prompt. The client reads an agent prompt, joins the matchmaking server through AXL, receives simulation state, uses Ollama to plan/chat/act, and exposes a local dashboard for wallet login, live state, chat, and decisions.

## Run

From the repo root:

```bash
uv sync
printf "Survive first. Make alliances, but protect critical resources." > prompt.txt
LOG_LEVEL=CLEAN CLIENT_WALLET_LOGIN_REQUIRED=false uv run --package client client prompt.txt
```

Start one client per agent. For a normal two-agent demo, run two clients with different prompt files after the server is running.

## Requirements

- Python 3.14+
- uv
- AXL running at `http://127.0.0.1:9002`
- Ollama running at `http://127.0.0.1:11434`
- A running The Last Prompt server

## Dashboard

Default client dashboard:

```text
http://127.0.0.1:8766
```

If `CLIENT_WALLET_LOGIN_REQUIRED=true`, open the dashboard, connect MetaMask on Sepolia, and use an ENS profile linked to the agent public key before matchmaking continues.

## Useful Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `AXL_BASE_URL` | `http://127.0.0.1:9002` | AXL transport endpoint |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `qwen3.5` | Local model used for decisions |
| `CLIENT_DASHBOARD_ENABLED` | `true` | Serve the local dashboard |
| `CLIENT_DASHBOARD_PORT` | `8766` | Dashboard port |
| `CLIENT_WALLET_LOGIN_REQUIRED` | `true` | Require MetaMask + ENS login |
| `CLIENT_WALLET_LOGIN_WAIT_SECONDS` | `0` | Wallet-login wait timeout; `0` waits indefinitely |
| `SERVER_PEER_ID` | empty | Optional expected server peer id override |

## Notes

- The prompt file is appended to the base survival prompt and should describe the agent's strategy.
- The client sends structured action batches only from the server-provided valid action list.
- Client replay data is saved by default under `/tmp/thelastprompt-client/`.
