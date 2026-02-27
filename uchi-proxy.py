#!/usr/bin/env python3
"""Tiny dual-stack TCP proxy: port 80 → VIBEDJ_PORT (default 6969)"""
import os, socket, threading

TARGET = int(os.environ.get('VIBEDJ_PORT', '6969'))

def _pipe(src, dst):
    try:
        while chunk := src.recv(65536):
            dst.sendall(chunk)
    except Exception:
        pass
    finally:
        for s in (src, dst):
            try: s.close()
            except: pass

def _handle(client):
    try:
        srv = socket.create_connection(('127.0.0.1', TARGET), timeout=10)
        threading.Thread(target=_pipe, args=(client, srv), daemon=True).start()
        threading.Thread(target=_pipe, args=(srv, client), daemon=True).start()
    except Exception:
        try: client.close()
        except: pass

sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET,   socket.SO_REUSEADDR, 1)
sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY,  0)  # dual-stack
sock.bind(('::', 80))
sock.listen(64)
print(f'proxy listening on :80 → localhost:{TARGET}', flush=True)
while True:
    client, _ = sock.accept()
    threading.Thread(target=_handle, args=(client,), daemon=True).start()
