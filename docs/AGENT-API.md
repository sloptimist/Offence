# Agent connection contract

Run a buyer-only Offence service on your PC, or use your own StartOS service. It
requires no GPU. Configure pinned routes with the StartOS Configure Buyer API
action, or the `gateway` object in the operator's configuration. Set
`OFFENCE_GATEWAY_API_KEY` to a random secret of at least 32 characters. Use HTTPS
for any connection outside loopback. API keys authenticate your agents to your
own service; they are never sent to inference providers.

Set these three values in an agent that supports the documented chat subset:

- Base URL: `https://<your-offence-address>/v1`
- API key: your private buyer API key
- Model: a configured route alias

`GET /v1/models` requires the bearer key and lists aliases, pinned provider/model
identities and supported capabilities. `GET /v1/providers` lists signed discovery
claims. Discovery never changes operator-pinned buyer routes. Policies can select among eligible signed offers automatically; see [Split jobs and routing](JOBS.md).
An agent can select among configured route or policy aliases by setting `model` on each request.

`POST /v1/chat/completions` accepts this shape:

```json
{
  "model": "my-model",
  "messages": [{"role": "user", "content": "Explain how this works."}],
  "max_tokens": 128,
  "stream": true,
  "temperature": 0,
  "n": 1
}
```

Only system, user and assistant roles with plain string content are accepted.
Maximum context input is 16,384 UTF-8 bytes and 64 messages. The backend also
checks tokenized context against the offered context cap. Unknown parameters,
media, tools, function calls, tool results, response formats, and arbitrary
backend options are rejected. This is a text-chat compatibility subset, not a
claim that every coding agent works. Reasoning-specific backend output is rejected
rather than silently discarded or billed as visible text. Use a text-output
configuration for the chosen model; Offence does not change the GPU server.

Streaming follows chat completion SSE chunks and `[DONE]` on success. Interrupted
streams carry an error and no success marker. Non-streaming replies carry the
assistant message and `offence.output_tokens`, `spent_msat`, and
`execution_verified`. Token counts include delivered end/control tokens. Counts
are not estimated from SSE messages or text length. Prompt usage is not fabricated.

## Operator configuration

```json
{
  "allowed_private_peers": ["http://<provider-lan-address>:8080"],
  "gateway": {
    "allow_free_lab": true,
    "max_concurrent": 2,
    "daily_output_tokens": 10000,
    "request_deadline_s": 120,
    "routes": [{
      "alias": "my-model",
      "endpoint": "http://<provider-lan-address>:8080",
      "provider": "<64-character-provider-public-key>",
      "model_id": "<64-character-model-manifest-hash>",
      "max_output_tokens": 512
    }]
  }
}
```

Placeholder values must be replaced. Local/DNS peer origins require explicit
operator approval; public literal-IP HTTPS and v3 onion origins follow the normal
peer rules. StartOS's buyer form requires each route origin in Approved LAN peers.
No request may override the route's endpoint, provider identity or manifest hash.

The buyer reserves the full requested output allowance for a rolling 24 hours,
before requesting a quote. Reservations persist across restarts and are not
refunded on cancellation or ambiguous failure. This conservative quota counts
concurrent attempts and prevents retries from silently bypassing limits. It is
not an invoice or a claim that all reserved tokens were generated.

All gateway requests have a zero payment budget. Paid quotes are rejected before
acceptance, and this gateway has no wallet. Free lab mode requires explicit
operator opt-in. Required-proof mode fails closed. Production payment policy and
routing-fee enforcement must be implemented and verified before enabling spending.

## Provider vLLM configuration

Set `backend` to `vllm`, `backend_url` to an operator-owned HTTP(S) origin without
paths, and `backend_model` to its exact served-model identifier. Configure the
model manifest and free offer as usual. A model name returned by vLLM is a claim,
not cryptographic execution proof. Never invent weight hashes from that name.

Offence sends only fixed text-generation parameters to `/tokenize`,
`/v1/completions`, and `/v1/chat/completions`. It requires exact streamed token IDs
and a valid completion marker. Redirects are refused. Provider secrets come from
`OFFENCE_BACKEND_API_KEY`, never buyer input. The adapter performs no remote tool
execution, file loading, URL retrieval or model administration.

Reference: [vLLM OpenAI-compatible server](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/).

Policy-routed chat identifies the selected provider and exact model in the non-streaming `offence` result, or the `X-Offence-Provider` and `X-Offence-Model-ID` streaming response headers.
