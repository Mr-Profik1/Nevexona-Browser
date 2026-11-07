#!/usr/bin/env python3
"""Measure real memory use of NEVEX AI (main process + all WebKit helper processes).

Needs a display:   xvfb-run -a python3 tools/measure_memory.py
Pages come from a local server, so no Internet is required.

PSS (proportional set size) is the fair number: it splits memory shared between
processes. RSS-sum is also printed but double-counts shared libraries.
Results depend on the machine, WebKitGTK version and pages; they are measurements
of this run only, not a general benchmark.
"""
import argparse
import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        n = self.path.strip("/") or "0"
        body = ("<!doctype html><title>Test page %s</title><body style='font:16px sans-serif'>"
                "<h1>Test page %s</h1>%s</body>" % (n, n, "<p>Lorem ipsum dolor sit amet.</p>" * 200)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def children_of(pid):
    out, parent = {pid}, {}
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                with open("/proc/%s/stat" % d) as f:
                    parent[int(d)] = int(f.read().rsplit(")", 1)[1].split()[1])
            except (OSError, IndexError, ValueError):
                pass
    changed = True
    while changed:
        changed = False
        for p, pp in parent.items():
            if pp in out and p not in out:
                out.add(p)
                changed = True
    return out


def kb(pid, field, path):
    try:
        with open("/proc/%d/%s" % (pid, path)) as f:
            for line in f:
                if line.startswith(field):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0


def sample(pid):
    procs = children_of(pid)
    pss = sum(kb(p, "Pss:", "smaps_rollup") for p in procs)
    rss = sum(kb(p, "VmRSS:", "status") for p in procs)
    return len(procs), pss / 1024.0, rss / 1024.0


def run_scenario(name, urls, session_tabs, reduced, settle, base):
    prof = tempfile.mkdtemp(prefix="nevex-mem-")
    if session_tabs:
        os.makedirs(os.path.join(prof, "config"), exist_ok=True)
        with open(os.path.join(prof, "config", "session.json"), "w") as f:
            json.dump({"tabs": [{"url": "%s/%d" % (base, i), "title": ""} for i in range(session_tabs)],
                       "active": 0}, f)
    cmd = [sys.executable, "-m", "nevex", "--profile", prof] + (["--reduced-memory"] if reduced else []) + urls
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    time.sleep(settle)
    alive = proc.poll() is None
    nproc, pss, rss = sample(proc.pid) if alive else (0, 0.0, 0.0)
    clean_exit = None
    if alive:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
            clean_exit = True
        except subprocess.TimeoutExpired:
            proc.kill()
            clean_exit = False
    err = proc.stderr.read().decode("utf-8", "replace")[-400:] if not alive else ""
    return {"scenario": name, "reduced_memory": reduced, "started": alive, "processes": nproc,
            "pss_mb": round(pss, 1), "rss_sum_mb": round(rss, 1), "exited_on_sigterm": clean_exit, "error": err}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--settle", type=float, default=12.0, help="seconds to wait before sampling")
    ap.add_argument("--json", help="write results to this file")
    args = ap.parse_args()

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_port

    scenarios = [
        ("start page, 1 tab", [], 0),
        ("1 loaded page", [base + "/1"], 0),
        ("5 pages open and loaded", ["%s/%d" % (base, i) for i in range(5)], 0),
        ("5-tab session restored (lazy: 1 loaded)", [], 5),
    ]
    results = []
    for reduced in (False, True):
        for name, urls, sess in scenarios:
            results.append(run_scenario(name, urls, sess, reduced, args.settle, base))
    srv.shutdown()

    print("\nMachine: %s, kernel %s, Python %s" % (platform.machine(), platform.release(), platform.python_version()))
    print("| Scenario | Reduced mode | Processes | PSS total (MB) | RSS sum (MB) | Clean exit on SIGTERM |")
    print("|---|---|---|---|---|---|")
    for r in results:
        if not r["started"]:
            print("| %s | %s | did not start | | | |\n%s" % (r["scenario"], r["reduced_memory"], r["error"]))
            continue
        print("| %s | %s | %d | %.1f | %.1f | %s |" % (r["scenario"], "yes" if r["reduced_memory"] else "no",
              r["processes"], r["pss_mb"], r["rss_sum_mb"], r["exited_on_sigterm"]))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=2)
    return 0 if all(r["started"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
