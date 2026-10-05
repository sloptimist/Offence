"""Real TCP gateway/provider/vLLM-contract fixture, no live GPU or wallet."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.smoke import port
from offence.crypto import Identity
from offence.models import Config, GatewayConfig, GatewayRoute, Manifest, Offer
import httpx


async def main():
    with tempfile.TemporaryDirectory(prefix='offence-gateway-') as directory:
        root = Path(directory)
        gpu_port, provider_port, buyer_port = [port() for _ in range(3)]
        provider_url = f'http://127.0.0.1:{provider_port}'
        model = Manifest(name='HTTP contract fixture', architecture='fixture', quantization='none', context_tokens=4096,
            artifacts=[{'path':'fixture.txt','sha256':'0'*64,'size':0,'role':'weights'}])
        provider_dir, buyer_dir = root / 'provider', root / 'buyer'
        identity = Identity.load(provider_dir / 'identity.key')
        buyer_dir.mkdir()
        config = Config(backend='vllm', backend_url=f'http://127.0.0.1:{gpu_port}', backend_model='fixture',
                        allow_lab_unverified=True, offer=Offer(manifest=model, output_msat_per_token=0, batch_tokens=2))
        (provider_dir / 'config.json').write_text(config.model_dump_json())
        buyer_config = Config(allowed_private_peers=[provider_url], gateway=GatewayConfig(allow_free_lab=True,
            routes=[GatewayRoute(alias='fixture', endpoint=provider_url, provider=identity.public, model_id=model.model_id)]))
        (buyer_dir / 'config.json').write_text(buyer_config.model_dump_json())
        fixture_code = '''
from http.server import BaseHTTPRequestHandler, HTTPServer
import json,sys,time
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_POST(self):
  data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  self.send_response(200)
  self.send_header('Content-Type','application/json' if self.path=='/tokenize' else 'text/event-stream')
  self.end_headers()
  if self.path=='/tokenize':
   self.wfile.write(b'{"count":2}'); return
  for text,ids,finish in [('hello',[1],None),(' world',[2],None),('',[3],'stop')]:
   frame={'model':'fixture','choices':[{'index':0,'delta':{'content':text},'token_ids':ids,'finish_reason':finish}]}
   self.wfile.write(('data: '+json.dumps(frame)+'\\n\\n').encode());self.wfile.flush();time.sleep(.02)
  self.wfile.write(b'data: [DONE]\\n\\n')
HTTPServer(('127.0.0.1',int(sys.argv[1])),Handler).serve_forever()
'''
        processes = []
        logs = []
        key = secrets.token_hex(32)
        try:
            for command in ([sys.executable,'-c',fixture_code,str(gpu_port)],
                            [sys.executable,'-m','offence.cli','serve','--data',str(provider_dir),'--port',str(provider_port)],
                            [sys.executable,'-m','offence.cli','serve','--data',str(buyer_dir),'--port',str(buyer_port)]):
                log = (root / f'{len(logs)}.log').open('wb'); logs.append(log)
                processes.append(subprocess.Popen(command, cwd=ROOT, env={**os.environ,'OFFENCE_GATEWAY_API_KEY':key},
                                                  stdout=log, stderr=log))
            async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{buyer_port}', trust_env=False, timeout=10,
                                         headers={'Authorization':'Bearer '+key}) as client:
                for _ in range(100):
                    try:
                        if (await client.get('/health')).status_code == 200: break
                    except httpx.HTTPError: pass
                    await asyncio.sleep(.1)
                payload={'model':'fixture','messages':[{'role':'user','content':'hi'}],'max_tokens':8,'stream':True}
                async with client.stream('POST','/v1/chat/completions',json=payload) as response:
                    assert response.status_code == 200, await response.aread()
                    chunks=[line async for line in response.aiter_lines() if line.startswith('data:')]
                assert chunks[-1]=='data: [DONE]',chunks
                records=[json.loads(c[6:]) for c in chunks[:-1]]
                assert ''.join(r['choices'][0]['delta'].get('content','') for r in records)=='hello world'
                assert (await client.post('/v1/chat/completions', json={**payload,'tools':[]})).status_code==400
                async with httpx.AsyncClient(trust_env=False) as probe:
                    assert (await probe.get(provider_url+'/v1/status')).json()['active_sessions']==0
            print(json.dumps({'gateway_tcp_stream':'passed','provider_tcp_stream':'passed',
                              'vllm_http_contract':'passed','unsupported_tools':'rejected',
                              'backend':'fixture','payments':'disabled'}))
        except Exception:
            for log in logs: log.flush()
            for path in root.glob('*.log'): print(path.read_text()[-3000:],file=sys.stderr)
            raise
        finally:
            for process in processes:
                process.terminate(); process.wait(timeout=5)
            for log in logs: log.close()


if __name__=='__main__':
    asyncio.run(main())
