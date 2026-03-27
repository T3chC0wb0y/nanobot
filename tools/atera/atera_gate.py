#!/usr/bin/env python3
import json
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ALERTS = Path('/tmp/atera-alerts.json')
ALERT_SCRIPT = str(BASE_DIR / 'atera_alerts.py')


def main():
    result = subprocess.run(
        ['python3', ALERT_SCRIPT, '--json'],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        print(json.dumps({
            'state': 'error',
            'stderr': (result.stderr or '').strip(),
            'stdout': (result.stdout or '').strip(),
        }))
        return 1

    raw = (result.stdout or '').strip()
    if not raw:
        print(json.dumps({'state': 'empty'}))
        return 0

    try:
        data = json.loads(raw)
    except Exception:
        print(json.dumps({'state': 'invalid', 'raw': raw[:4000]}))
        return 1

    alerts = data.get('alerts') or []
    if not alerts:
        print(json.dumps({'state': 'no_alerts'}))
        return 0

    ALERTS.write_text(json.dumps({'alerts': alerts}, indent=2))
    print(json.dumps({'state': 'alerts', 'alerts': alerts}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
