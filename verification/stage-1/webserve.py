#!/usr/bin/env python3
"""Local fixture web server: one port per fixture site (each is its own host root, with its own robots.txt).
Ports: verified 8801, nameaddr 8802, noproof 8803, wrongco 8804, robots 8805, redirect-to-metadata 8806, slow 8807,
403 8808, 429 8809. Logs every request to logs/webserve-requests.log (so crawling decisions are observable)."""
import http.server, os, sys, threading, time, socketserver
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "web")
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "webserve-requests.log")
SITES = {8801: "verified", 8802: "nameaddr", 8803: "noproof", 8804: "wrongco", 8805: "robots",
         8806: "@redirect", 8807: "@slow", 8808: "@403", 8809: "@429"}
lock = threading.Lock()

def handler(port, site):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(s, *a, **k): super().__init__(*a, directory=os.path.join(ROOT, site) if not site.startswith("@") else ROOT, **k)
        def log_message(s, fmt, *args):
            with lock, open(LOG, "a") as f: f.write(f"{time.strftime('%H:%M:%S')} {port} {site} {s.command} {s.path} {s.headers.get('User-Agent')}\n")
        def do_GET(s):
            if site == "@redirect":
                s.send_response(302); s.send_header("Location", "http://169.254.169.254/latest/meta-data/"); s.end_headers(); s.log_message(""); return
            if site == "@slow":
                s.log_message(""); time.sleep(60); s.send_response(200); s.end_headers(); return
            if site in ("@403", "@429"):
                s.send_response(int(site[1:])); s.send_header("Retry-After", "1"); s.end_headers(); s.log_message(""); return
            return super().do_GET()
    return H

class TS(socketserver.ThreadingMixIn, http.server.HTTPServer): daemon_threads = True; allow_reuse_address = True
os.makedirs(os.path.dirname(LOG), exist_ok=True)
for p, s in SITES.items():
    threading.Thread(target=TS(("127.0.0.1", p), handler(p, s)).serve_forever, daemon=True).start()
print("serving", SITES, flush=True)
while True: time.sleep(3600)
