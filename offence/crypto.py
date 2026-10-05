"""Versioned signatures and authenticated, payment-keyed batch encryption."""
import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305


def canonical(value) -> bytes:
    def check(v):
        if isinstance(v, dict):
            if not all(isinstance(k, str) for k in v):
                raise ValueError("JSON keys must be strings")
            for item in v.values():
                check(item)
        elif isinstance(v, list):
            for item in v:
                check(item)
        elif v is not None and type(v) not in (str, int, bool):
            raise ValueError("Wire format allows strings, integers, booleans and null only")
        elif type(v) is int and abs(v) > 2**53 - 1:
            raise ValueError("Integer exceeds interoperable JSON range")
    check(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def b64(value: bytes) -> str:
    return base64.b64encode(value).decode()


def unb64(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


class Identity:
    def __init__(self, key=None):
        self.key = key or Ed25519PrivateKey.generate()

    @classmethod
    def load(cls, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return cls(Ed25519PrivateKey.from_private_bytes(path.read_bytes()))
        key = Ed25519PrivateKey.generate()
        with os.fdopen(fd, "wb") as handle:
            handle.write(key.private_bytes_raw())
            handle.flush()
            os.fsync(handle.fileno())
        return cls(key)

    @property
    def public(self):
        return self.key.public_key().public_bytes_raw().hex()

    def sign(self, body: dict) -> dict:
        message = {"signer": self.public, "body": body}
        return {**message, "signature": self.key.sign(b"offence/v1\0" + canonical(message)).hex()}


def verify(envelope: dict, expected: str | None = None) -> dict:
    if not isinstance(envelope, dict) or set(envelope) != {"signer", "body", "signature"}:
        raise ValueError("Invalid signature envelope")
    if expected is not None and envelope["signer"] != expected:
        raise ValueError("Unexpected signer")
    try:
        message = {"signer": envelope["signer"], "body": envelope["body"]}
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(envelope["signer"])).verify(
            bytes.fromhex(envelope["signature"]), b"offence/v1\0" + canonical(message))
    except Exception as exc:
        raise ValueError("Invalid signature") from exc
    if not isinstance(envelope["body"], dict):
        raise ValueError("Body must be an object")
    return envelope["body"]


def seal(payload: dict, header: dict, preimage: bytes) -> dict:
    # Domain separated key; a payment preimage is not reused across batches.
    key = hashlib.sha256(b"offence/batch-key/v1\0" + preimage).digest()
    nonce = os.urandom(12)
    ciphertext = ChaCha20Poly1305(key).encrypt(nonce, canonical(payload), canonical(header))
    return {"header": header, "nonce": b64(nonce), "ciphertext": b64(ciphertext),
            "payment_hash": hashlib.sha256(preimage).hexdigest()}


def unseal(batch: dict, preimage: bytes) -> dict:
    if hashlib.sha256(preimage).hexdigest() != batch["payment_hash"]:
        raise ValueError("Payment preimage does not match batch")
    key = hashlib.sha256(b"offence/batch-key/v1\0" + preimage).digest()
    plain = ChaCha20Poly1305(key).decrypt(unb64(batch["nonce"]), unb64(batch["ciphertext"]),
                                        canonical(batch["header"]))
    return json.loads(plain)
