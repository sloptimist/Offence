"""Signed quotes and encrypted incremental delivery. No execution-proof shortcut."""
import asyncio
from contextlib import aclosing
import hashlib
import json
import secrets
import time

from .backend import batches
from .crypto import b64, digest, seal, verify, unb64
from .models import Request


class ProofUnavailable(ValueError):
    pass


class Provider:
    def __init__(self, config, identity, store, backend, wallet=None):
        self.config, self.identity, self.store = config, identity, store
        self.backend, self.wallet = backend, wallet
        self.pending = {}
        self.running = set()
        self.recovery_offset = 0

    @property
    def active(self):
        return len(self.running)

    def release(self, session):
        self.running.discard(session)

    def quote(self, envelope):
        request = Request.model_validate(verify(envelope))
        if abs(request.issued - int(time.time())) > 60:
            raise ValueError("Request timestamp outside window")
        if request.network != self.config.network:
            raise ValueError("Request network mismatch")
        if request.provider != self.identity.public:
            raise ValueError("Wrong provider")
        if request.proof_policy == "required":
            raise ProofUnavailable("Execution proof is not implemented; verified inference is blocked")
        if request.proof_policy == "lab-unverified":
            if not self.config.allow_lab_unverified or self.config.lightning in {"lnd-mainnet", "strike"}:
                raise ProofUnavailable("Lab inference disabled or mainnet selected")
        elif not self.config.allow_seller_claim:
            raise ValueError("Seller-claim inference is disabled")
        offer = self.config.offer
        if not offer or not offer.available or not self.backend:
            raise ValueError("Provider unavailable")
        if offer.manifest.model_id != request.model_id:
            raise ValueError("Model identity mismatch")
        if request.max_output_tokens > offer.max_output_tokens:
            raise ValueError("Output limit exceeds offer")
        if request.messages and not hasattr(self.backend, "stream_chat"):
            raise ValueError("Provider does not support text chat")
        maximum = request.max_output_tokens * offer.output_msat_per_token
        if maximum > request.max_total_msat:
            raise ValueError("Price exceeds buyer budget")
        if maximum and self.wallet is None:
            raise ValueError("Paid lab inference requires regtest LND")
        settlement_mode = getattr(self.wallet, 'settlement_mode', 'preimage-v1') if maximum else 'preimage-v1'
        if settlement_mode == 'provider-key-v1' and not request.allow_provider_key_release:
            raise ValueError('Buyer must explicitly accept supplier-dependent key recovery')
        now = int(time.time())
        self.pending = {k: v for k, v in self.pending.items() if v[0]["body"]["expires"] > now}
        if self.active + len(self.pending) >= self.config.max_sessions:
            raise ValueError("Provider capacity reserved")
        session_id = digest(envelope)
        body = {"type": "quote", "network": request.network, "session": session_id,
                "buyer": envelope["signer"], "model_id": request.model_id,
                "request_hash": session_id, "expires": now + 60,
                "max_output_tokens": request.max_output_tokens, "max_total_msat": maximum,
                "output_msat_per_token": offer.output_msat_per_token, "batch_tokens": offer.batch_tokens,
                "generation_deadline_s": offer.generation_deadline_s,
                "payment_timeout_s": offer.payment_timeout_s, "proof": "unavailable",
                "payment_network": getattr(self.wallet, "network", "regtest") if maximum else "free-lab",
                "assurance": request.proof_policy, "settlement_mode": settlement_mode}
        quote = self.identity.sign(body)
        # Durable unique request ID prevents replay after restart.
        # Conservatively reserve the entire offered context, including template
        # overhead and requested output. Identity rotation does not reset this limit.
        self.store.admit(session_id, offer.manifest.context_tokens,
                         self.config.max_requests_per_hour, self.config.max_work_tokens_per_hour)
        self.store.session(session_id, envelope["signer"], quote)
        self.pending[session_id] = (quote, request)
        return quote

    async def reconcile(self):
        if self.wallet is None:
            return
        pending = self.store.unsettled_batches(offset=self.recovery_offset)
        self.recovery_offset = self.recovery_offset + len(pending) if len(pending) == 32 else 0
        for session, seq, envelope in pending:
            sealed = envelope["body"]["sealed"]
            amount = sealed["header"]["amount_msat"]
            if amount and await self.batch_settled(session, seq, envelope["body"]):
                self.store.paid(session, seq)

    async def batch_settled(self, session, seq, body):
        amount = body['sealed']['header']['amount_msat']
        if body.get('settlement_mode') != 'provider-key-v1':
            return await self.wallet.settled(body['sealed']['payment_hash'], amount)
        row = self.store.db.execute('SELECT paid FROM batches WHERE session=? AND seq=?', (session,seq)).fetchone()
        if row and row[0]:
            return True
        if getattr(self.wallet, 'settlement_mode', None) != 'provider-key-v1':
            raise ValueError('Original hosted wallet is required for reconciliation')
        saved = self.store.hosted_batch(session, seq)
        return await self.wallet.settled_batch(saved['reference'], body['invoice_payment_hash'], amount)

    async def release_key(self, envelope):
        request = verify(envelope)
        if (set(request) != {'type','session','sequence','batch_hash','payment_preimage','issued'}
                or request['type'] != 'release-key' or type(request['issued']) is not int
                or abs(request['issued']-time.time()) > 60 or type(request['sequence']) is not int):
            raise ValueError('Invalid key request')
        row = self.store.db.execute('SELECT s.buyer,b.envelope FROM sessions s JOIN batches b ON b.session=s.id WHERE s.id=? AND b.seq=?',
                                    (request['session'], request['sequence'])).fetchone()
        if not row or row[0] != envelope['signer']:
            raise ValueError('Key request buyer mismatch')
        batch = json.loads(row[1])
        if not batch or digest(batch) != request['batch_hash'] or batch['body'].get('settlement_mode') != 'provider-key-v1':
            raise ValueError('Key request does not match batch')
        proof = bytes.fromhex(request['payment_preimage'])
        if len(proof) != 32 or hashlib.sha256(proof).hexdigest() != batch['body']['invoice_payment_hash']:
            raise ValueError('Invalid payment proof')
        if not await self.batch_settled(request['session'], request['sequence'], batch['body']):
            raise ValueError('Payment is not confirmed credited')
        self.store.paid(request['session'], request['sequence'])
        saved = self.store.hosted_batch(request['session'], request['sequence'])
        return self.identity.sign({'type':'batch-key','session':request['session'],
            'sequence':request['sequence'],'batch_hash':digest(batch),'key':saved['key'], 'buyer':envelope['signer']})

    def accept(self, envelope):
        body = verify(envelope)
        if set(body) != {"type", "session", "quote_hash"} or body["type"] != "accept":
            raise ValueError("Invalid quote acceptance")
        entry = self.pending.get(body["session"])
        if not entry:
            raise ValueError("Quote unavailable or already accepted")
        quote, request = entry
        if (quote["body"]["buyer"] != envelope["signer"] or digest(quote) != body["quote_hash"]
                or quote["body"]["expires"] <= time.time()):
            raise ValueError("Quote acceptance mismatch or expiry")
        del self.pending[body["session"]]
        self.running.add(body["session"])
        return quote, request

    async def stream(self, quote, request):
        q = quote["body"]
        session, previous, total, seq = q["session"], digest(quote), 0, 0
        started, first_batch_ms = time.monotonic(), None
        finish_reason = None
        try:
            self.store.state(session, "running")
            # Includes payment waits so slow/nonpaying buyers cannot hold capacity forever.
            async with asyncio.timeout(q["generation_deadline_s"]):
                source = (self.backend.stream_chat([m.model_dump() for m in request.messages], request.max_output_tokens)
                          if request.messages else self.backend.stream(request.prompt, request.max_output_tokens))
                async def track_completion():
                    nonlocal finish_reason
                    async for group in source:
                        if group.get("finish_reason") in {"stop", "length"} and not group.get("token_ids"):
                            finish_reason = group["finish_reason"]
                        else:
                            yield group
                async with aclosing(source), aclosing(track_completion()) as tracked:
                    async for groups in batches(tracked, q["batch_tokens"]):
                        count = sum(len(group["token_ids"]) for group in groups)
                        total += count
                        if total > q["max_output_tokens"]:
                            raise ValueError("Backend exceeded quoted output budget")
                        amount = count * q["output_msat_per_token"]
                        header = {"session": session, "sequence": seq, "previous": previous,
                                  "model_id": q["model_id"], "request_hash": q["request_hash"],
                                  "token_count": count, "total_tokens": total, "amount_msat": amount}
                        preimage = secrets.token_bytes(32)
                        sealed = seal({"groups": groups}, header, preimage)
                        commitment = digest(sealed)
                        hosted = None
                        if amount and q.get('settlement_mode') == 'provider-key-v1':
                            issued = await self.wallet.create_batch_invoice(amount, commitment, q['payment_timeout_s'])
                            invoice = issued['invoice']
                            hosted = {'key':b64(preimage), 'reference':issued['reference']}
                        else:
                            invoice = await self.wallet.invoice(preimage, amount, commitment, q["payment_timeout_s"]) if amount else None
                        body = {"type": "batch", "sealed": sealed, "invoice": invoice,
                                "proof": "unavailable", "free_key": b64(preimage) if not amount else None}
                        if hosted:
                            body.update(settlement_mode='provider-key-v1', invoice_payment_hash=issued['payment_hash'])
                        envelope = self.identity.sign(body)
                        # Persist before sending. Buyer retains ciphertext and can recover it.
                        self.store.batch(session, seq, envelope, hosted=hosted)
                        if first_batch_ms is None:
                            first_batch_ms = int((time.monotonic() - started) * 1000)
                        yield envelope
                        if amount:
                            if hosted:
                                end = time.monotonic() + q['payment_timeout_s']
                                while not await self.batch_settled(session, seq, body):
                                    if time.monotonic() >= end:
                                        raise TimeoutError('Payment deadline exceeded')
                                    await asyncio.sleep(2)
                            elif not await self.wallet.wait(sealed["payment_hash"], amount, q["payment_timeout_s"]):
                                raise TimeoutError("Payment deadline exceeded")
                            self.store.paid(session, seq)
                        previous = digest(envelope)
                        seq += 1
            self.store.state(session, "complete")
            yield self.identity.sign({"type": "end", "session": session, "previous": previous,
                                      "total_tokens": total, "batches": seq,
                                      "finish_reason": finish_reason or ("length" if total == q["max_output_tokens"] else "stop")})
        except asyncio.CancelledError:
            self.store.state(session, "interrupted")
            raise
        except GeneratorExit:
            self.store.state(session, "interrupted")
            raise
        except Exception as exc:
            self.store.state(session, "failed")
            yield self.identity.sign({"type": "error", "session": session,
                                      "code": type(exc).__name__, "previous": previous,
                                      "message": "Stream stopped; retain delivered batches and payment records"})
        finally:
            try:
                self.store.observe(session, first_batch_ms, int((time.monotonic() - started) * 1000))
            finally:
                self.release(session)
