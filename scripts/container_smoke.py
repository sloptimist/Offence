"""Run inside the built image via stdin; tests the image's own application."""
import json
import subprocess
import sys
import tempfile
import time
import urllib.request

with tempfile.TemporaryDirectory(prefix="offence-container-") as data:
    process = subprocess.Popen([sys.executable, "-m", "offence.cli", "serve", "--data", data, "--port", "18080"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen("http://127.0.0.1:18080/health", timeout=1) as response:
                    health = json.load(response)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Image did not become healthy")
        assert health["production_payments"] == "blocked"
        with urllib.request.urlopen("http://127.0.0.1:18080/") as response:
            assert b"Model identity is a seller claim" in response.read()
        print(json.dumps({"container_http": "passed", "production_payments": "blocked"}))
    finally:
        process.terminate()
        process.wait(timeout=5)
