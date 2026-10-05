"""Real TCP, three-process test. Uses no GPU, Lightning funds, or live service."""
import asyncio
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from offence.client import Buyer
from offence.crypto import Identity
from offence.models import Manifest


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def main():
    with tempfile.TemporaryDirectory(prefix="offence-smoke-") as directory:
        root = Path(directory)
        ports = [port() for _ in range(3)]
        urls = [f"http://127.0.0.1:{p}" for p in ports]
        fixture = b"protocol fixture, not language model weights\n"
        model = Manifest(name="Protocol fixture", architecture="protocol-fixture", quantization="none",
                         context_tokens=4096, artifacts=[{"path": "fixture.txt", "size": len(fixture),
                         "sha256": hashlib.sha256(fixture).hexdigest(), "role": "weights"}])
        processes, logs = [], []
        def start(index):
            log = (root / f"{index}.log").open("ab")
            logs.append(log)
            process = subprocess.Popen([sys.executable, "-m", "offence.cli", "serve", "--data", str(root / str(index)),
                                        "--port", str(ports[index])], cwd=ROOT, stdout=log, stderr=log)
            processes.append(process)
            return process
        try:
            for i in range(3):
                data = root / str(i)
                data.mkdir()
                (data / "config.json").write_text(json.dumps({
                    "endpoint": urls[i], "seeds": [urls[(i + 1) % 3]] if i < 2 else [urls[1]],
                    "allowed_private_peers": urls, "gossip_interval_s": 1,
                    "backend": "fixture", "allow_lab_unverified": True,
                    "offer": {"manifest": model.model_dump(), "output_msat_per_token": 0, "batch_tokens": 2}}))
                start(i)
            async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                async def wait_ready(url):
                    for _ in range(100):
                        try:
                            r = await client.get(url + "/v1/status")
                            if r.status_code == 200:
                                return r.json()
                        except httpx.HTTPError:
                            pass
                        await asyncio.sleep(0.1)
                    raise AssertionError("Node did not start")
                states = [await wait_ready(url) for url in urls]
                for _ in range(100):
                    listings = [(await client.get(url + "/v1/providers")).json()["providers"] for url in urls]
                    if all(len(p) == 3 for p in listings):
                        break
                    await asyncio.sleep(0.1)
                assert all(len(p) == 3 for p in listings), "Transitive discovery failed"
                buyer = Buyer(Identity.load(root / "buyer" / "identity.key"), root / "buyer")
                async def buy(index):
                    parts = [x async for x in buyer.run(urls[index], states[index]["identity"], model.model_id,
                                                       "hello", 8, 0, allow_lab=True)]
                    assert "".join(parts) == "This is a lab fixture."
                await buy(0)
                processes[0].terminate()
                processes[0].wait(timeout=5)
                await buy(1)
                processes[1].terminate()
                processes[1].wait(timeout=5)
                start(1)
                restored = await wait_ready(urls[1])
                assert restored["identity"] == states[1]["identity"]
                await buy(1)
                assert (await client.get(urls[1] + "/health")).json()["production_payments"] == "blocked"
                assert "Model identity is a seller claim" in (await client.get(urls[1])).text
            print(json.dumps({"nodes": 3, "transitive_discovery": "passed", "streamed_purchases": 3,
                              "seed_loss": "passed", "identity_restart": "passed",
                              "production_gate": "closed", "backend": "fixture", "payments": "free"}))
        except Exception:
            for path in root.glob("*.log"):
                print(path.read_text()[-4000:], file=sys.stderr)
            raise
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
            for log in logs:
                log.close()


if __name__ == "__main__":
    asyncio.run(main())
