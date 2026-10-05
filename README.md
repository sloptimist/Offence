# Offence

## Buyer app

Download the buyer app from [offence.ai](https://offence.ai), or run
`python -m offence.buyer_launcher` in the installed Python environment.
No GPU is needed. See [buyer setup](buyer-download/README.md) for installation,
agent connection, wallet configuration and security boundaries.


A permissionless inference service for StartOS and Linux Docker. Providers advertise
exact model identities and seller-defined prices. Buyers select a provider and
receive streamed output through a signed delivery protocol.

Read [the specification](SPEC.md) for protocol rules and
[the research review](docs/RESEARCH.md) for Bitcoin Core connectivity, BitTorrent,
other inference networks, proof systems, and Lightning tradeoffs.
Implementation and deployment status live in [AGENTS.md](AGENTS.md).

## Local development

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pytest -q
.venv/bin/python scripts/smoke.py
npm ci --ignore-scripts
npm run check
npm run build
```

The smoke test runs three temporary localhost nodes, discovers peers transitively,
streams protocol-fixture output, removes a bootstrap node, and restarts another node.
It does not use GPU inference or real Lightning payments.

## Run a node

```sh
.venv/bin/python -m offence.cli serve --data data --port 8080
```

Open `http://127.0.0.1:8080`. Configure the node through `data/config.json` before
starting it; use [the free lab example](examples/free-lab.json) for a protocol demo.
A new node has no mandatory seed or central registration service. Add a peer address
from an operator you know. Discovering a peer does not automatically purchase inference.

For a real GPU backend, use `backend: "llamacpp"`, set its base `backend_url`, and
provide a manifest for its exact model. The llama.cpp completion stream must return
real token IDs; character estimates and one-SSE-message-per-token assumptions are
rejected. A lab experiment does not prove which model the GPU server executes.

## Docker and StartOS

See [GitHub Docker build downloads](docs/DOCKER-BUILDS.md) for architecture-specific
image archives, checksum verification and installation. To build locally:

```sh
docker build -t offence:lab .
docker run --rm --name offence-lab \
  -p 127.0.0.1:8080:8080 -v offence-data:/data offence:lab
```

The default container runs discovery without inference until configured. Use a
Docker volume or bind mount for persistent configuration and identity.
See [package instructions](instructions.md) for StartOS configuration, model file
verification, the buyer CLI, recovery, and regtest wallet integration.

## Contributing

MIT licensed. No central admission mechanism or network asset is part of the design.
Keep execution proof separate from identity signatures and reputation claims.
See [AGENTS.md](AGENTS.md) for contribution rules and [ROADMAP.md](ROADMAP.md) for work.

For agent connection details, see [Agent API](docs/AGENT-API.md). For supplier controls and deployment boundaries, see [Provider security](docs/PROVIDER-SECURITY.md).

[Automatic routing and split jobs](docs/JOBS.md) describes the policy API for agents and apps.
