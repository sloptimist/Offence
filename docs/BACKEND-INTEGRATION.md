# Testing a real inference backend

This opt-in runner starts a temporary loopback-only Offence provider, completes a
free request, disconnects a buyer after output arrives, and checks that another
request succeeds. It terminates the provider directly and fails if shutdown needs
forced termination. Provider and buyer files are deleted after the run.

First run the CPU fixture to check the runner itself:

```sh
.venv/bin/python scripts/backend_integration.py --fixture
```

For real inference, reserve the hardware through your existing allocation process
and start a compatible backend separately. Wait for model loading and kernel
initialization to finish. The backend must return exact token IDs. Use an isolated
environment with restricted networking, no wallet credentials, no management
sockets and no writable model mounts. A Nix shell alone provides no isolation.

```sh
.venv/bin/python scripts/backend_integration.py \
  --backend vllm \
  --backend-url http://127.0.0.1:8000 \
  --backend-model YOUR_SERVED_MODEL_NAME \
  --manifest manifest.json \
  --model-directory /read-only-model
```

For llama.cpp, select `--backend llamacpp` and omit `--backend-model`.
`--model-directory` verifies artifact sizes and hashes before requests. When the
backend runs elsewhere, verify its files there before running the test. Neither
hashes nor the served model name prove which computation the backend executes.
An optional `OFFENCE_BACKEND_API_KEY` is passed only to the test provider. It is
never included in the report. Do not send a key to an untrusted backend origin.

The runner uses no discovery seeds or wallet, charges zero, allows one session,
limits output to 64 tokens and generation to 30 seconds, and bounds admitted
work. The supplied manifest controls the context limit. It does not start or
stop the inference backend, enforce its resource limits, or configure its network.
Use backend-side limits appropriate for the hardware you reserved.

The JSON report contains token counts, observed provider slot release time and
shutdown status. It excludes prompts, output text, identities, backend addresses
and local paths. Failures return only an exception type; provider logs and
transient records are discarded. It does not measure GPU cancellation latency:
slot release is an application observation. A fast backend may finish before the
buyer disconnects. Backend metrics are needed to establish actual cancellation.

Exit status is zero only when all checks and graceful provider shutdown pass.
The CPU fixture verifies protocol plumbing; real backend compatibility requires
running the operator-selected backend. Live payments, sustained load, separate
buyer hosts and public discovery require additional tests.
