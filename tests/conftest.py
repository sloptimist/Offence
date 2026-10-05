import hashlib
import time

import pytest

from offence.crypto import Identity
from offence.models import Config, Manifest, Offer


@pytest.fixture
def manifest():
    data = b"protocol fixture, not language model weights\n"
    return Manifest(name="Protocol fixture", architecture="protocol-fixture", quantization="none",
                    context_tokens=4096, artifacts=[{"path": "fixture.txt", "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(), "role": "weights"}])


@pytest.fixture
def config(manifest):
    return Config(backend="fixture", allow_lab_unverified=True,
                  offer=Offer(manifest=manifest, output_msat_per_token=0, batch_tokens=2))


def request(identity, provider, manifest, **changes):
    import secrets
    body = {"type": "request", "network": "offence-lab-v1", "provider": provider,
            "model_id": manifest.model_id, "nonce": secrets.token_hex(32), "issued": int(time.time()),
            "prompt": "hello", "max_output_tokens": 8, "max_total_msat": 0,
            "proof_policy": "lab-unverified"}
    body.update(changes)
    return identity.sign(body)
