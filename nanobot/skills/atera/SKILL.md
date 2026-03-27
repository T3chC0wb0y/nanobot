---
name: atera
description: "Work with Atera tickets using the local Python helper for triage, comments, updates, and urgent checks."
metadata: {"nanobot":{"emoji":"🎫","requires":{"bins":["python3"]}}}
---

# Atera Skill

Use the local helper at `<repo>/tools/atera/atera_tickets.py` for Atera ticket work. Resolve `<repo>` from the current nanobot checkout.

## Credential loading

The helper reads credentials from:
- `ATERA_API_KEY`
- `ATERA_API_KEY_FILE`
- `$NANOBOT_WORKSPACE/secrets/atera_api_key`
- `~/.nanobot/workspace/secrets/atera_api_key`

Optional:
- `ATERA_BASE_URL` (defaults to `https://app.atera.com/api/v3`)

Do not print API keys or paste secrets into chat unless the user explicitly asks.

## Common commands

List active tickets:
```bash
python3 tools/atera/atera_tickets.py triage --statuses Open,Pending --items 50 --limit 20
```

Show high-priority active tickets:
```bash
python3 tools/atera/atera_tickets.py high --statuses Open,Pending --items 50 --limit 20
```

Show tickets waiting on us:
```bash
python3 tools/atera/atera_tickets.py needs-response --statuses Open,Pending --items 50 --limit 20
```

Show tickets waiting on the user:
```bash
python3 tools/atera/atera_tickets.py pending-user --statuses Open,Pending --items 50 --limit 20
```

Bucket tickets by next action:
```bash
python3 tools/atera/atera_tickets.py action-queue --statuses Open,Pending --items 50 --limit-per-bucket 5
```

Get one ticket by `TicketID`:
```bash
python3 tools/atera/atera_tickets.py get <ticket_id>
```

List comments by `TicketID`:
```bash
python3 tools/atera/atera_tickets.py comments <ticket_id> --page 1 --items 25
```

Add a comment by `TicketID`:
```bash
python3 tools/atera/atera_tickets.py comment-add <ticket_id> "text"
```

Update a ticket by `TicketID`:
```bash
python3 tools/atera/atera_tickets.py update <ticket_id> --status Pending --priority High
```

Urgent alert check:
```bash
python3 tools/atera/atera_alerts.py
```

JSON urgent alert check:
```bash
python3 tools/atera/atera_alerts.py --json
```

Cheap gate for automation:
```bash
python3 tools/atera/atera_gate.py
```

## Guidance

- Prefer read-only commands first when validating connectivity.
- Queue views print `TicketNumber` and `TicketID` together when both are present, for example `#12345 (id:67890)`.
- Use `TicketID` for `get`, `comments`, `comment-add`, and `update`.
- Use `waiting_on()`-based views instead of status alone for triage.
- Before posting comments or updating tickets, summarize the intended change briefly.
- Treat `comment-add` and `update` as live actions.
- For recurring urgent checks, use `HEARTBEAT.md` rather than a one-time reminder.
