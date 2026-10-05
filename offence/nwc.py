"""Buyer-only NWC adapter. The connected wallet controls Lightning routing fees."""
import asyncio
from datetime import timedelta
import hashlib
import re
import time
from urllib.parse import parse_qs, urlsplit

from .bolt11 import decode_invoice


def validate_connection(value):
    # Owner input only. Never accept a connection from supplier advertisements.
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError('Invalid wallet connection')
    p = urlsplit(value)
    q = parse_qs(p.query, strict_parsing=True)
    if (p.scheme != 'nostr+walletconnect' or not re.fullmatch('[0-9a-f]{64}', p.netloc)
            or p.path not in ('', '/') or p.fragment
            or set(q) - {'relay', 'secret', 'lud16'}
            or len(q.get('secret', [])) != 1
            or not re.fullmatch('[0-9a-f]{64}', q['secret'][0])
            or not 1 <= len(q.get('relay', [])) <= 3):
        raise ValueError('Invalid wallet connection')
    for relay in q['relay']:
        r = urlsplit(relay)
        if (r.scheme != 'wss' or not r.hostname or r.username or r.password or r.fragment
                or len(relay) > 1024):
            raise ValueError('Wallet relays must use secure WebSockets')
    return value


class NwcWallet:
    network = 'mainnet'
    fee_policy = 'wallet-managed'

    def __init__(self, connection, client=None):
        from nostr_sdk import NostrWalletConnectUri, NostrWalletConnectBuilder
        validate_connection(connection)
        try:
            uri = NostrWalletConnectUri.parse(connection)
            self.client = client or NostrWalletConnectBuilder(uri).timeout(timedelta(seconds=20)).build()
        except Exception:
            raise ValueError('Invalid wallet connection') from None
        self.identity = hashlib.sha256(connection.encode()).hexdigest()

    async def close(self):
        await self.client.client().shutdown()

    async def check_network(self):
        from nostr_sdk import Method
        async with asyncio.timeout(25):
            info = await self.client.get_info()
        if info.network != 'mainnet' or any(m not in info.methods for m in
                (Method.GET_INFO(), Method.PAY_INVOICE(), Method.LOOKUP_INVOICE())):
            raise ValueError('Wallet requires mainnet and payment recovery permissions')

    @staticmethod
    def preimage(value, payment_hash):
        if not isinstance(value, str) or not re.fullmatch('[0-9a-fA-F]{64}', value):
            raise ValueError('Invalid payment proof')
        result = bytes.fromhex(value)
        if hashlib.sha256(result).hexdigest() != payment_hash:
            raise ValueError('Payment proof mismatch')
        return result

    async def pay(self, invoice, payment_hash, amount_msat, commitment, fee_limit_msat):
        from nostr_sdk import PayInvoiceRequest
        if fee_limit_msat != 0:
            raise ValueError('NWC cannot enforce an Offence routing-fee limit')
        decoded = decode_invoice(invoice)
        if (decoded['payment_hash'] != payment_hash or decoded['amount_msat'] != amount_msat
                or decoded['description_hash'] != commitment or decoded['expires'] <= time.time()):
            raise ValueError('Invoice differs from the signed batch or is expired')
        await self.check_network()
        # Exactly one send. Timeouts remain unknown and are reconciled read-only.
        async with asyncio.timeout(25):
            result = await self.client.pay_invoice(PayInvoiceRequest(id=None, invoice=invoice, amount=None))
        return self.preimage(result.preimage, payment_hash)

    async def track(self, payment_hash, amount_msat, fee_limit_msat):
        from nostr_sdk import LookupInvoiceRequest, TransactionType
        if not re.fullmatch('[0-9a-f]{64}', payment_hash) or fee_limit_msat != 0:
            raise ValueError('Invalid recovery request')
        try:
            async with asyncio.timeout(25):
                result = await self.client.lookup_invoice(LookupInvoiceRequest(payment_hash=payment_hash, invoice=None))
        except Exception:
            return {'status': 'UNKNOWN'}
        if (result.payment_hash != payment_hash or result.amount != amount_msat
                or result.transaction_type != TransactionType.OUTGOING):
            raise ValueError('Payment recovery contract mismatch')
        # Absence, expiry and failure reports never release an uncertain reservation.
        if not result.preimage or not result.settled_at:
            return {'status': 'UNKNOWN'}
        preimage = self.preimage(result.preimage, payment_hash)
        if type(result.fees_paid) is not int or result.fees_paid < 0:
            raise ValueError('Invalid wallet fee report')
        return {'status': 'SUCCEEDED', 'preimage': preimage.hex(), 'fee_msat': result.fees_paid}
