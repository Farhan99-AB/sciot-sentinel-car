# planner_runner.py — v3 (Fixed filename & exposed errors)
import subprocess
import re
import os

# FIXED: Match your original exact filename (missing 'e')
DOMAIN_FILE  = "domain_sentinel.pddl" 
PROBLEM_FILE = "problem_sentinel.pddl"

PLAN_LINE_PATTERN = re.compile(r'^\d+:\s*\(([a-zA-Z0-9_-]+(?:\s+[a-zA-Z0-9_-]+)*)\)\s*$')

def run_planner() -> list[str]:
    # CRITICAL FIX: Delete the old solution file so Pyperplan is forced to generate a new one
    soln_path = PROBLEM_FILE + ".soln"
    if os.path.exists(soln_path):
        os.remove(soln_path)

    try:
        result = subprocess.run(
            ["python3", "-m", "pyperplan", "--search", "bfs", DOMAIN_FILE, PROBLEM_FILE],
            capture_output=True, text=True, timeout=10
        )

        # CRITICAL FIX: Print the exact error if Pyperplan crashes
        if result.returncode != 0:
            print(f"[Planner] Pyperplan failed with exit code {result.returncode}")
            print(f"[Planner] STDERR: {result.stderr}")

        actions = []
        for line in result.stdout.splitlines():
            line = line.strip()
            match = PLAN_LINE_PATTERN.match(line)
            if match:
                actions.append(match.group(1).lower())

        # Fallback: Read newly generated solution file
        if not actions:
            actions = _read_solution_file()

        print(f"[Planner] Parsed plan: {actions}")
        return actions

    except subprocess.TimeoutExpired:
        print("[Planner] Timeout — using fallback")
        return []
    except Exception as e:
        # CRITICAL FIX: Print the actual exception instead of hiding it
        print(f"[Planner] CRITICAL ERROR: {e}")
        return []

def _read_solution_file() -> list[str]:
    soln_path = PROBLEM_FILE + ".soln"
    if not os.path.exists(soln_path):
        print(f"[Planner] No solution file found at {soln_path}")
        return []

    actions = []
    with open(soln_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("(") and line.endswith(")"):
                actions.append(line.strip("()").lower())

    print(f"[Planner] Read from solution file: {actions}")
    return actions