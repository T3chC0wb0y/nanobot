#!/usr/bin/env python3
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HELPER_PATH = Path(__file__).resolve().with_name('atera_tickets.py')
spec = importlib.util.spec_from_file_location('atera_helper', HELPER_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

STATE_DIR = Path.home() / '.local' / 'state' / 'atera-alerts'
STATE_FILE = STATE_DIR / 'state.json'
STATE_DIR.mkdir(parents=True, exist_ok=True)


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def severity(ticket):
    txt = mod.ticket_text(ticket)
    pr = (ticket.get('TicketPriority') or '').lower()
    score = 0
    reasons = []

    if pr == 'critical':
        score += 4
        reasons.append('priority=critical')
    elif pr in {'high', 'urgent'}:
        score += 3
        reasons.append(f'priority={pr}')

    critical_words = [
        'outage', 'down', 'cannot work', "can't work", 'locked out', 'cannot login', "can't login",
        'unable to login', 'email down', 'server down', 'internet down', 'network down',
        'cannot print', 'payroll', 'finance', 'urgent', 'asap', 'immediately', 'emergency'
    ]
    high_words = [
        'crash', 'crashing', 'not working', 'cannot access', 'unable to access', 'message trace',
        'offboard', 'onedrive', 'sharepoint', 'outlook', 'adobe', 'indesign', 'intune'
    ]

    for word in critical_words:
        if word in txt:
            score += 2
            reasons.append(word)
            break

    for word in high_words:
        if word in txt:
            score += 1
            reasons.append(word)
            break

    if any(x in txt for x in ['multiple users', 'everyone', 'all staff', 'entire office', 'school office']):
        score += 2
        reasons.append('broad impact')

    return score, reasons


def latest_ts(ticket):
    return max([
        mod.parse_dt(ticket.get('LastEndUserCommentTimestamp')) or datetime(1970, 1, 1, tzinfo=timezone.utc),
        mod.parse_dt(ticket.get('LastTechnicianCommentTimestamp')) or datetime(1970, 1, 1, tzinfo=timezone.utc),
        mod.parse_dt(ticket.get('TicketCreatedDate')) or datetime(1970, 1, 1, tzinfo=timezone.utc),
    ]).astimezone(timezone.utc).isoformat()


def collect_alerts():
    state = load_state()
    tickets = mod.gather_active(['Open', 'Pending'], 100)
    alerts = []

    for t in tickets:
        score, reasons = severity(t)
        if score < 3:
            continue
        key = str(t.get('TicketID'))
        ts = latest_ts(t)
        wait = mod.waiting_on(t)
        pr = (t.get('TicketPriority') or '').lower()
        if wait != 'us' and pr not in {'critical', 'high', 'urgent'}:
            continue
        if state.get(key) == ts:
            continue
        alerts.append((score, t, reasons, ts))
        state[key] = ts

    save_state(state)
    alerts.sort(key=lambda x: x[0], reverse=True)
    return alerts


def render_text(alerts):
    if not alerts:
        return 'NO_REPLY'

    lines = ['Atera urgent check:']
    for score, t, reasons, _ in alerts[:5]:
        reason_text = ', '.join(reasons[:3]) if reasons else 'threshold'
        lines.append(
            f"- #{t.get('TicketNumber') or t.get('TicketID')} | {t.get('TicketStatus')} | {t.get('CustomerName') or '-'} | {t.get('TicketTitle') or '-'} | score {score} | wait:{mod.waiting_on(t)} | reasons:{reason_text}"
        )
    return '\n'.join(lines)


def render_json(alerts):
    items = []
    for score, t, reasons, ts in alerts[:5]:
        items.append({
            'ticket_id': t.get('TicketID'),
            'ticket_number': t.get('TicketNumber') or t.get('TicketID'),
            'status': t.get('TicketStatus'),
            'priority': t.get('TicketPriority'),
            'customer': t.get('CustomerName'),
            'title': t.get('TicketTitle'),
            'score': score,
            'waiting_on': mod.waiting_on(t),
            'reasons': reasons,
            'timestamp': ts,
        })
    return json.dumps({'alerts': items}, indent=2)


def main():
    alerts = collect_alerts()
    if '--json' in sys.argv:
        print(render_json(alerts))
    else:
        print(render_text(alerts))


if __name__ == '__main__':
    main()
