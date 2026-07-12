# incident_logger.py — Saves event data for the dashboard graph
import json
from datetime import datetime
from pathlib import Path

LOG_FILE = Path("incidents_log.json")

def get_log():
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text())
        except json.JSONDecodeError:
            return []
    return []

def log_incident(scenario: str, state: dict, plan: list):
    log = get_log()
    
    log.append({
        "timestamp": datetime.now().isoformat(),
        "scenario": scenario,
        "temperature": state.get("temperature_cabin", 0),
        "occupant_detected": state.get("occupant_detected", False),
        "plan_steps": len(plan),
        "plan": plan
    })
    
    # Keep log size manageable (last 100 events)
    if len(log) > 100:
        log = log[-100:]
        
    LOG_FILE.write_text(json.dumps(log, indent=2))
    return log