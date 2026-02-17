#!/usr/bin/env python3
"""
Deploy server.js to cloud and restart Node + api-signals.
Run from lab-trading-dashboard folder (or set LAB_DASHBOARD_DIR).

Usage:
  python3 scripts/deploy-server-to-cloud.py
  # or from repo root:
  python3 lab-trading-dashboard/scripts/deploy-server-to-cloud.py
"""

import os
import subprocess
import sys

# Cloud server
HOST = "root@150.241.244.130"
REMOTE_DIR = "/root/lab-trading-dashboard/server/"
REMOTE_SERVER_JS = REMOTE_DIR + "server.js"

# Resolve lab-trading-dashboard dir (script may be run from lab-trading-dashboard or repo root)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAB_DASHBOARD = os.path.dirname(SCRIPT_DIR)
LOCAL_SERVER_JS = os.path.join(LAB_DASHBOARD, "server", "server.js")


def run(cmd, check=True, shell=False):
    print("$", cmd if isinstance(cmd, str) else " ".join(cmd))
    if isinstance(cmd, str) and shell:
        return subprocess.run(cmd, shell=True)
    return subprocess.run(cmd, shell=shell, check=check)


def main():
    if not os.path.isfile(LOCAL_SERVER_JS):
        print("Error: server.js not found at", LOCAL_SERVER_JS, file=sys.stderr)
        sys.exit(1)

    print("Deploying server.js to cloud and restarting services...")
    print()

    # 1. SCP server.js
    run(["scp", LOCAL_SERVER_JS, f"{HOST}:{REMOTE_SERVER_JS}"])
    print("  OK: server.js copied\n")

    # 2. Restart lab-trading-dashboard (Node)
    run(["ssh", HOST, "sudo systemctl restart lab-trading-dashboard"])
    print("  OK: lab-trading-dashboard restarted\n")

    # 3. Start api-signals (idempotent: start is fine if already running)
    run(["ssh", HOST, "sudo systemctl start api-signals"])
    print("  OK: api-signals started\n")

    print("Done. Check: ssh", HOST, '"systemctl status lab-trading-dashboard api-signals"')


if __name__ == "__main__":
    main()
