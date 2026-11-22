"""Smoke check: sign in as each role through /dev/login-as and load its key pages.

Usage: uv run .claude/skills/run-integrated/smoke.py [--base http://127.0.0.1:5000]
"""
import sys

import requests

BASE = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--base" else "http://127.0.0.1:5000"

PAGES = {
    None: ["/", "/login", "/register", "/about", "/schools", "/donations"],
    "learner": ["/learner/", "/learner/learn/subjects"],
    "volunteer": ["/volunteer/"],
    "teacher": ["/teacher/", "/teacher/people", "/teacher/attendance", "/teacher/worksheets"],
    "school_admin": ["/school/"],
    "administrator": ["/admin/dashboard", "/admin/users", "/admin/schools", "/admin/donations"],
}

failures = 0
for role, paths in PAGES.items():
    session = requests.Session()
    if role:
        signed_in = session.get(f"{BASE}/dev/login-as", params={"type": role, "survey": 1, "map_test": 1})
        if signed_in.status_code != 200:
            print(f"[FAIL] sign in as {role}: {signed_in.status_code}")
            failures += 1
            continue
    for path in paths:
        response = session.get(f"{BASE}{path}")
        ok = response.status_code == 200
        failures += not ok
        print(f"[{'OK' if ok else 'FAIL'}] {role or 'public'} {path}: {response.status_code}")

sys.exit(1 if failures else 0)
