from copy import deepcopy
import os

import pytest
from cryptography.exceptions import InvalidTag

from offence.crypto import Identity, canonical, seal, unseal, verify
from offence.models import Artifact


def test_identity_survives_restart_and_key_is_private(tmp_path):
    path = tmp_path / "identity.key"
    one = Identity.load(path)
    assert Identity.load(path).public == one.public
    assert path.stat().st_mode & 0o777 == 0o600


def test_signature_covers_signer_and_entire_body():
    node = Identity()
    envelope = node.sign({"price": 20})
    assert verify(envelope, node.public) == {"price": 20}
    envelope["body"]["price"] = 10
    with pytest.raises(ValueError):
        verify(envelope)


@pytest.mark.parametrize("value", [1.1, float("nan"), {"a": 2**54}, {1: "bad"}])
def test_ambiguous_json_rejected(value):
    with pytest.raises(ValueError):
        canonical(value)


def test_payment_key_authenticates_ciphertext_and_header():
    preimage = os.urandom(32)
    batch = seal({"text": "answer"}, {"session": "1", "tokens": 1}, preimage)
    assert unseal(batch, preimage) == {"text": "answer"}
    with pytest.raises(ValueError):
        unseal(batch, os.urandom(32))
    batch["header"]["tokens"] = 2
    with pytest.raises(InvalidTag):
        unseal(batch, preimage)


def test_model_identity_independent_of_mirror_and_changes_with_weights(manifest):
    copy = manifest.model_copy(deep=True)
    copy.sources = ["https://huggingface.co/example", "https://another.example/model"]
    assert copy.model_id == manifest.model_id
    copy.artifacts[0].sha256 = "0" * 64
    assert copy.model_id != manifest.model_id


def test_model_file_hash_and_path_escape(manifest, tmp_path):
    (tmp_path / "fixture.txt").write_bytes(b"protocol fixture, not language model weights\n")
    manifest.verify_files(tmp_path)
    (tmp_path / "fixture.txt").write_bytes(b"changed")
    with pytest.raises(ValueError):
        manifest.verify_files(tmp_path)
    with pytest.raises(ValueError):
        Artifact(path="../secret", role="weights", size=0, sha256="0" * 64)
