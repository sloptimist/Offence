from copy import deepcopy

import httpx
import pytest

from offence.app import create_app
from offence.client import Buyer
from offence.crypto import Identity, verify
from offence.evidence import verify_delivery


async def test_public_receipts_require_opt_in_and_do_not_claim_execution(config, manifest, tmp_path):
    app = create_app(tmp_path / "node", config, background=False)
    p = app.state.provider
    buyer = Buyer(Identity(), tmp_path / "buyer")
    _ = [x async for x in buyer.run("http://node", p.identity.public, manifest.model_id, "hi", 8, 0,
                                   allow_lab=True, transport=httpx.ASGITransport(app=app))]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://node") as client:
        assert (await client.get("/v1/evidence")).status_code == 403
        config.share_receipts = True
        envelope = (await client.get("/v1/evidence")).json()
        package = verify(envelope, p.identity.public)["packages"][0]
        assert verify_delivery(package)["payment_settlement_verified"] is False
        corrupted = deepcopy(package)
        corrupted["receipt"]["body"]["received_tokens"] += 1
        with pytest.raises(ValueError):
            verify_delivery(corrupted)
        record = verify((await client.get("/v1/track-record")).json(), p.identity.public)
        assert record["latency_samples"] == 1
        assert record["execution_verified"] is False


def test_invalid_unknown_config_cannot_enable_mainnet():
    from offence.models import Config
    with pytest.raises(ValueError):
        Config(lightning="lnd-mainnet")
    with pytest.raises(ValueError):
        Config(production_payments=True)
