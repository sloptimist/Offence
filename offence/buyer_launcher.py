"""Local desktop launcher with one process per buyer data directory."""
import argparse
import os
from pathlib import Path
import sys
import socket
import threading
import webbrowser


def main():
    parser = argparse.ArgumentParser(description='Offence buyer app, no GPU required')
    parser.add_argument('--data', type=Path, default=Path.home() / '.offence-buyer')
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Use a port between 1024 and 65535')
    os.umask(0o077)
    args.data.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (args.data / 'buyer.lock').open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit('This buyer data directory is already in use. Open the existing app.')
    from .buyer_app import create_buyer_app, local_key
    import uvicorn
    app = create_buyer_app(args.data, port=args.port)
    sock = socket.socket()
    try:
        sock.bind(('127.0.0.1', args.port))
    except OSError:
        raise SystemExit('Buyer port is unavailable. Choose another port with --port.')
    url = f'http://127.0.0.1:{args.port}/#' + local_key(args.data / 'owner.key')
    print('Offence buyer runs only on this computer. Stop with Ctrl+C.')
    print('Private owner link (do not share with agents):\n' + url, flush=True)
    timer = None
    if not args.no_browser:
        timer = threading.Timer(2, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()
    try:
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port, access_log=False,
                                proxy_headers=False, limit_concurrency=16, timeout_keep_alive=5))
        server.run(sockets=[sock])
    finally:
        if timer:
            timer.cancel()
        sock.close()
        lock.close()


if __name__ == '__main__':
    main()
