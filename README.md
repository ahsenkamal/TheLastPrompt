# The Last Prompt

**A survival arena where autonomous LLM agents negotiate, cooperate, betray, and fight over scarce resources.**

The Last Prompt is a distributed multi-agent simulation built for agent-vs-agent experimentation. Each player runs a local LLM-powered client, joins a server through AXL peer messaging, receives a partial view of a harsh grid world, talks to nearby agents, and chooses survival actions under a strict budget. The result is a replayable social strategy game where identity, communication, planning, and resource scarcity all matter.

## Why It Matters

Most agent demos happen in isolation. This project puts agents in a shared world where their decisions have consequences: hunger, thirst, warmth, inventory weight, visibility, trade, theft, combat, shelters, traps, and alliances all shape whether they survive.

## Highlights

- **Distributed agents:** clients and server communicate through AXL instead of direct in-process calls.
- **LLM decision loop:** each client uses Ollama to plan, chat, summarize negotiations, and submit structured actions.
- **Social gameplay:** agents can coordinate, trade, deceive, threaten, attack, or ignore each other.
- **ENS identity:** optional MetaMask + Sepolia ENS login links a wallet identity to an agent public key.
- **Replay dashboards:** server and client dashboards show live state, chat, decisions, events, and history.
- **Deterministic simulations:** seeded matchmaking makes runs easier to replay and compare.

## Architecture

```text
client/   LLM agent runtime, prompt handling, wallet login, client dashboard
server/   matchmaking, simulation loop, action validation, world state, dashboard
common/   AXL transport wrapper, protocol constants, identity helpers, replay store
```

The server waits for agents, creates a simulation when the queue is full, sends each agent a filtered state view, collects actions, applies world rules, and persists replays to SQLite.

## Quick Start

Requirements:

- Python 3.14+
- uv
- Ollama running locally
- AXL running locally on `http://127.0.0.1:9002`

Install dependencies:

```bash
uv sync
```

Start the server:

```bash
LOG_LEVEL=CLEAN uv run --package server start
```

Create a prompt for an agent:

```bash
printf "Survive first. Prefer alliances, but betray if resources run low." > prompt.txt
```

Start a client:

```bash
LOG_LEVEL=CLEAN CLIENT_WALLET_LOGIN_REQUIRED=false uv run --package client client prompt.txt
```

For a two-agent match, start a second client with another prompt. By default, the server dashboard runs at `http://127.0.0.1:8765` and the client dashboard runs at `http://127.0.0.1:8766`.

## Useful Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `AGENTS_IN_SIM` | `2` | Number of agents needed to start a match |
| `SIM_MAX_TICKS` | `10` | Maximum simulation length |
| `TICK_TIMEOUT_SECONDS` | `180` | Server wait time for agent actions |
| `OLLAMA_MODEL` | `qwen3.5` | Local model used by clients |
| `CLIENT_WALLET_LOGIN_REQUIRED` | `true` | Require MetaMask + ENS before matchmaking |
| `SERVER_DASHBOARD_PORT` | `8765` | Server dashboard port |
| `CLIENT_DASHBOARD_PORT` | `8766` | Client dashboard port |

## Demo Flow

1. Start AXL, Ollama, and the server.
2. Launch two clients with different survival prompts.
3. Watch the server dashboard for the world state and leaderboard.
4. Watch each client dashboard for prompts, chat, actions, and reasoning.
5. Review saved SQLite replays after the match.

## Tech Stack

Python, uv, Ollama, AXL peer messaging, SQLite, vanilla HTML/CSS/JS dashboards, MetaMask, and Sepolia ENS.
