#!/usr/bin/env python3
"""timed.py OUT.json -- cmd...  : run cmd, record exit code, wall seconds, children peak RSS (KB)."""
import json, resource, subprocess, sys, time
out = sys.argv[1]; cmd = sys.argv[sys.argv.index("--") + 1:]
t = time.time(); rc = subprocess.call(cmd); w = time.time() - t
json.dump({"cmd": cmd, "exit_code": rc, "wall_s": round(w, 2),
           "peak_rss_kb": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss}, open(out, "w"))
print(f"[timed] exit={rc} wall={w:.1f}s"); sys.exit(rc)
