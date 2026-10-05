"""Buyer verification and durable ciphertext retention before any regtest payment."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import time

import httpx
from .crypto import canonical, digest, unb64, unseal, verify


class Buyer:
    def __init__(self, identity, directory: Path, wallet=None):
        self.identity, self.directory, self.wallet = identity, directory, wallet
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.record_limit = 64 * 1024 * 1024
        self.record_bytes = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())

    def save(self, name, value):
        # Ciphertexts and recovered keys are private local records. Never gossip them.
        destination = self.directory / name
        temporary = self.directory / (name + ".tmp")
        encoded = canonical(value)
        old_size = destination.stat().st_size if destination.exists() else 0
        if self.record_bytes - old_size + len(encoded) > self.record_limit:
            raise ValueError("Buyer evidence storage limit reached")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        if os.name != "nt":
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        self.record_bytes += len(encoded) - old_size

    async def reconcile_payments(self):
        """Recover payment keys without ever sending a payment or restarting GPU work."""
        if self.wallet is None:
            raise ValueError("Payment recovery requires a regtest wallet")
        results = []
        for path in sorted(self.directory.glob("*.attempt.json")):
            name = path.name.removesuffix(".attempt.json")
            if (self.directory / (name + ".payment.json")).exists():
                continue
            attempt = json.loads(path.read_text())
            if attempt.get("network", "regtest") != getattr(self.wallet, "network", "regtest"):
                continue
            batch = json.loads((self.directory / (name + ".batch.json")).read_text())
            body = verify(batch, attempt["provider"])
            sealed = body["sealed"]
            if (digest(batch) != attempt["batch_hash"] or digest(sealed) != attempt["commitment"]
                    or body.get("invoice_payment_hash", sealed["payment_hash"]) != attempt["payment_hash"]
                    or sealed["header"]["amount_msat"] != attempt["amount_msat"]):
                raise ValueError("Payment recovery evidence mismatch")
            result = await self.wallet.track(attempt["payment_hash"], attempt["amount_msat"],
                                             attempt["fee_limit_msat"])
            if result["status"] == "SUCCEEDED":
                preimage = bytes.fromhex(result["preimage"])
                # Keep the key even if the provider supplied invalid ciphertext.
                self.save(name + ".payment.json", {"preimage": preimage.hex(),
                    "amount_msat": attempt["amount_msat"], "fee_msat": result["fee_msat"]})
            results.append({"batch": name, "status": result["status"]})
        return results

    async def fetch_key(self, client, provider, batch, payment_preimage):
        from .discovery import read_json
        header = batch['body']['sealed']['header']
        if hashlib.sha256(payment_preimage).hexdigest() != batch['body']['invoice_payment_hash']:
            raise ValueError('Payment proof differs from invoice')
        request = self.identity.sign({'type':'release-key','session':header['session'],
            'sequence':header['sequence'],'batch_hash':digest(batch),
            'payment_preimage':payment_preimage.hex(),'issued':int(time.time())})
        # Strike may report payment completion after the buyer receives its preimage.
        # A failed/unknown result preserves the payment record for explicit recovery.
        deadline = time.monotonic() + 30
        while True:
            async with client.stream('POST','/v1/release-key',json=request) as response:
                if response.status_code != 400 or time.monotonic() >= deadline:
                    result = verify(await read_json(response), provider)
                    break
            await asyncio.sleep(2)
        if (result.get('type') != 'batch-key' or result.get('buyer') != self.identity.public
                or result.get('session') != header['session'] or result.get('sequence') != header['sequence']
                or result.get('batch_hash') != digest(batch)):
            raise ValueError('Invalid supplier key release')
        key = unb64(result['key'])
        unseal(batch['body']['sealed'], key)
        return key

    async def recover_hosted_keys(self, endpoint, provider, transport=None, tor_proxy=None):
        # The caller supplies the endpoint explicitly; never follow a recovery URL
        # from a remote invoice, webhook, or an unsigned payment result.
        results = []
        async with httpx.AsyncClient(base_url=endpoint, transport=transport, proxy=tor_proxy,
                timeout=40, trust_env=False, follow_redirects=False) as client:
            for path in sorted(self.directory.glob('*.payment.json')):
                name = path.name.removesuffix('.payment.json')
                batch = json.loads((self.directory/(name+'.batch.json')).read_text())
                if batch['signer'] != provider:
                    continue
                body = verify(batch, provider)
                if body.get('settlement_mode') != 'provider-key-v1':
                    continue
                payment = json.loads(path.read_text())
                key = await self.fetch_key(client, provider, batch, bytes.fromhex(payment['preimage']))
                self.save(name+'.key.json', {'key':key.hex()})
                payload = unseal(body['sealed'],key)
                h = body['sealed']['header']
                groups = payload['groups']
                if (sum(len(g['token_ids']) for g in groups) != h['token_count']
                        or any(type(t) is not int or t < 0 for g in groups for t in g['token_ids'])
                        or any(not isinstance(g['text'],str) for g in groups)):
                    raise ValueError('Recovered token content differs from contract')
                receipt = self.identity.sign({'type':'receipt','session':h['session'],'sequence':h['sequence'],
                    'batch_hash':digest(batch),'payment_hash':body['invoice_payment_hash'], 'received_tokens':h['token_count']})
                self.save(name+'.receipt.json',receipt)
                try:
                    async with client.stream('POST','/v1/receipt',json=receipt): pass
                except httpx.HTTPError: pass
                results.append({'batch':name,'text':''.join(g['text'] for g in groups),'tokens':h['token_count']})
        return results

    async def run(self, endpoint, provider, model_id, prompt, max_tokens, max_msat,
                  allow_lab=False, fee_limit_msat=1000, transport=None, tor_proxy=None, messages=None, detailed=False, assurance=None, total_fee_limit_msat=1000, daily_limit_msat=0, allow_provider_key_release=False):
        assurance = assurance or ("lab-unverified" if allow_lab else "required")
        if assurance not in {"lab-unverified", "seller-claim"}:
            raise ValueError("Execution proof unavailable; buyer refuses unverified inference")
        if getattr(self.wallet, "network", None) == "mainnet" and assurance != "seller-claim":
            raise ValueError("Mainnet requires explicit seller-claim assurance")
        if type(total_fee_limit_msat) is not int or total_fee_limit_msat < 0:
            raise ValueError("Invalid total routing fee limit")
        if type(fee_limit_msat) is not int or fee_limit_msat < 0:
            raise ValueError("Invalid per-batch routing fee limit")
        reserved_fees = 0
        network = "offence-v1" if getattr(self.wallet, "network", None) == "mainnet" else "offence-lab-v1"
        body = {"type": "request", "network": network,
            "provider": provider, "model_id": model_id, "nonce": secrets.token_hex(32),
            "issued": int(time.time()), "prompt": prompt, "max_output_tokens": max_tokens,
            "max_total_msat": max_msat, "proof_policy": assurance}
        if allow_provider_key_release:
            body["allow_provider_key_release"] = True
        if messages is not None:
            body["messages"] = messages
        from .models import Request
        Request.model_validate(body)
        request = self.identity.sign(body)
        async with httpx.AsyncClient(base_url=endpoint, transport=transport, proxy=tor_proxy,
                                     timeout=180, trust_env=False, follow_redirects=False) as client:
            from .discovery import read_json
            async with client.stream("POST", "/v1/quote", json=request) as response:
                quote = await read_json(response)
            q = verify(quote, provider)
            if (q.get("type") != "quote" or q.get("network") != network
                    or q.get("session") != digest(request) or q.get("request_hash") != digest(request)
                    or q.get("model_id") != model_id or q.get("buyer") != self.identity.public
                    or q.get("max_output_tokens") != max_tokens or q.get("max_total_msat", max_msat + 1) > max_msat
                    or q.get("expires", 0) <= time.time()
                    or type(q.get("output_msat_per_token")) is not int or q["output_msat_per_token"] < 0
                    or q["max_total_msat"] != max_tokens * q["output_msat_per_token"]
                    or type(q.get("batch_tokens")) is not int or not 1 <= q["batch_tokens"] <= 128
                    or q.get("proof") != "unavailable"
                    or q.get("assurance", "lab-unverified") != assurance
                    or q.get("payment_network") != (getattr(self.wallet, "network", "regtest") if q["max_total_msat"] else "free-lab")):
                raise ValueError("Provider quote violates buyer request")
            if q["max_total_msat"] and not self.wallet:
                raise ValueError("Paid quote requires a configured buyer wallet before acceptance")
            mode = q.get('settlement_mode', 'preimage-v1')
            if mode not in {'preimage-v1','provider-key-v1'} or (mode == 'provider-key-v1' and not allow_provider_key_release):
                raise ValueError('Unaccepted settlement mode')
            # A batch can contain fewer tokens than its maximum (byte limits or
            # backend groups). Reserve for one paid batch per output token rather
            # than assuming every batch will be full and failing after GPU work.
            if q["max_total_msat"] and max_tokens * fee_limit_msat > total_fee_limit_msat:
                raise ValueError("Total routing fee budget cannot cover worst-case batch count")
            session = q["session"]
            if q["max_total_msat"] and getattr(self.wallet, "network", None) == "mainnet":
                from .spending import reserve
                reserve(self.directory, session, q["max_total_msat"], total_fee_limit_msat, daily_limit_msat)
            self.save(session + ".quote.json", quote)
            acceptance = self.identity.sign({"type": "accept", "session": session, "quote_hash": digest(quote)})
            previous, total, spent, seq, ended = digest(quote), 0, 0, 0, False
            async with client.stream("POST", "/v1/stream", json=acceptance) as response:
                response.raise_for_status()
                buffer = b""
                async for chunk in response.aiter_bytes():
                    buffer += chunk
                    if len(buffer) > 1024 * 1024:
                        raise ValueError("Provider stream buffer exceeded")
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        message = json.loads(line)
                        body = verify(message, provider)
                        if ended:
                            raise ValueError("Data after stream end")
                        if body.get("type") == "error":
                            self.save(session + ".error.json", message)
                            raise ValueError("Provider stream failed; received tokens remain recorded")
                        if body.get("type") == "end":
                            if (body.get("session") != session or body.get("previous") != previous
                                    or body.get("total_tokens") != total or body.get("batches") != seq):
                                raise ValueError("Invalid completion record")
                            finish_reason = body.get("finish_reason", "length" if total == max_tokens else "stop")
                            if finish_reason not in {"stop", "length"}:
                                raise ValueError("Unsupported completion reason")
                            ended = True
                            self.save(session + ".end.json", message)
                            continue
                        if body.get("type") != "batch" or body.get("proof") != "unavailable":
                            raise ValueError("Unexpected message or unsupported proof claim")
                        sealed = body["sealed"]
                        h = sealed["header"]
                        count = h.get("token_count")
                        amount = h.get("amount_msat")
                        if (h.get("session") != session or h.get("sequence") != seq or h.get("previous") != previous
                                or h.get("model_id") != model_id or h.get("request_hash") != digest(request)
                                or type(count) is not int or not 1 <= count <= q["batch_tokens"]
                                or h.get("total_tokens") != total + count or total + count > max_tokens
                                or type(amount) is not int or amount != count * q["output_msat_per_token"]
                                or spent + amount > max_msat):
                            raise ValueError("Invalid batch ordering, token count, or billing")
                        if body.get('settlement_mode', 'preimage-v1') != mode:
                            raise ValueError('Batch settlement differs from quote')
                        payment_hash = body.get('invoice_payment_hash', sealed['payment_hash'])
                        if mode == 'provider-key-v1' and (not isinstance(payment_hash, str) or len(payment_hash) != 64
                                or len(bytes.fromhex(payment_hash)) != 32 or not amount):
                            raise ValueError('Invalid hosted payment hash')
                        name = f"{session}.{seq}"
                        self.save(name + ".batch.json", message)
                        if amount:
                            if not self.wallet or body.get("free_key") is not None:
                                raise ValueError("Paid batch requires a regtest wallet")
                            if reserved_fees + fee_limit_msat > total_fee_limit_msat:
                                raise ValueError("Total routing fee budget exhausted")
                            reserved_fees += fee_limit_msat
                            # Conservatively reserve the full fee cap, even on successful payments.
                            # Persist the intent before dispatch. Unknown outcomes are reconciled,
                            # never inferred to be failures and never automatically resubmitted.
                            self.save(name + ".attempt.json", {
                                "payment_hash": payment_hash, "amount_msat": amount,
                                "commitment": digest(sealed), "fee_limit_msat": fee_limit_msat,
                                "invoice": body["invoice"], "batch_hash": digest(message),
                                "provider": provider, "session": session, "sequence": seq,
                                "network": getattr(self.wallet, "network", "regtest")})
                            preimage = await self.wallet.pay(body["invoice"], payment_hash, amount,
                                                            digest(sealed), fee_limit_msat)
                            self.save(name + ".payment.json", {"preimage": preimage.hex(), "amount_msat": amount})
                            if mode == 'provider-key-v1':
                                preimage = await self.fetch_key(client, provider, message, preimage)
                                self.save(name + '.key.json', {'key':preimage.hex()})
                        else:
                            if body.get("invoice") is not None:
                                raise ValueError("Unexpected invoice for a free batch")
                            preimage = unb64(body["free_key"])
                        payload = unseal(sealed, preimage)
                        groups = payload["groups"]
                        if (not isinstance(groups, list) or sum(len(g["token_ids"]) for g in groups) != count
                                or any(type(t) is not int or t < 0 for g in groups for t in g["token_ids"])
                                or any(not isinstance(g["text"], str) for g in groups)):
                            raise ValueError("Decrypted token count or content differs from contract")
                        receipt = self.identity.sign({"type": "receipt", "session": session,
                            "sequence": seq, "batch_hash": digest(message),
                            "payment_hash": payment_hash, "received_tokens": count})
                        self.save(name + ".receipt.json", receipt)
                        # Receipt delivery failure must not discard already received output.
                        try:
                            async with client.stream("POST", "/v1/receipt", json=receipt):
                                pass
                        except httpx.HTTPError:
                            pass
                        total += count
                        spent += amount
                        seq += 1
                        previous = digest(message)
                        text = "".join(g["text"] for g in groups)
                        yield {"type": "delta", "text": text, "token_count": count, "session": session, "amount_msat": amount} if detailed else text
                if buffer.strip() or not ended:
                    raise ValueError("Stream interrupted without a signed completion record")

                if q["max_total_msat"] and getattr(self.wallet, "network", None) == "mainnet":
                    from .spending import complete
                    complete(self.directory, session)
                if detailed:
                    yield {"type": "end", "finish_reason": finish_reason}
