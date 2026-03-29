---
name: atera
description: "Work with Atera tickets using the local Python helper for triage, structured context, comments, status changes, resolutions, and urgent watch checks."
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
- `ATERA_TECHNICIAN_ID`
- `ATERA_TECHNICIAN_EMAIL`

Do not print API keys or paste secrets into chat unless the user explicitly asks.

## Beta operating model

This workflow is in **beta approval mode**.

### Core rule
- Do **not** do any ticket work, post any user-facing comment, change any live ticket field, or resolve any ticket without Bob's approval.

### Approval gates
1. If the ticket looks safely autonomous, prepare a short work plan and send Bob a **Teams DM** asking approval **before doing any work**.
2. After work is completed, send Bob a **Teams DM** showing:
   - what was completed
   - the exact end-user message you want to send
   - that you intend to resolve the ticket
3. Wait for Bob's approval again before posting the comment and resolving.

### Allowed autonomous scope in beta
Only consider tickets that are fully within autonomous scope, such as:
- simple factual questions the agent can answer confidently
- straightforward low-risk tasks the agent can complete without the user being present
- repeatable tasks the agent has already been taught and can perform safely

### Out of scope / silent defer
If the ticket likely requires the user to be logged in, remote support, live collaboration, ambiguous troubleshooting, risky judgment, security-sensitive changes, billing/account changes, or anything outside safe scope:
- do not reply
- do not acknowledge receipt
- do not tell the user to schedule time
- do not partially work the ticket
- leave it for Bob

## Reply style for end users
Only send an end-user reply **after the work is actually done** and Bob has approved the exact message.

Rules:
- brief
- non-technical language
- say what was done, not how
- do not quote the user's message back to them
- do not restate the whole issue unless needed
- do not send placeholder progress replies
- do not send scheduling language

Good examples:
- `Hi Elaine,\nThe automatic reply has been updated.\nThank you,`
- `Hi John,\nYour access has been restored.\nThank you,`
- `Hi Sarah,\nThe requested change has been made.\nThank you,`

## High-priority watch / escalation
If a ticket looks likely high priority or high impact:
- do not work it autonomously unless Bob explicitly approves
- add it to the watch list
- use recurring checks every 10 minutes while it remains watched
- send Bob a **Teams DM** when the ticket is first flagged and when there is a meaningful change

Use `HEARTBEAT.md` for recurring watch checks rather than a one-time reminder.

## Official v3 API task map
Use this as the authoritative mapping for common ticket tasks.

### Read ticket
- `GET /api/v3/tickets/{ticketId}`
- Returns ticket details including fields such as `EndUserID`, `EndUserEmail`, `EndUserFirstName`, and `EndUserLastName`.

### Create ticket
- `POST /api/v3/tickets`
- Requires at least:
  - `EndUserID`
  - `TicketTitle`
  - `Description`
- Optional ticket fields include:
  - `TicketPriority`
  - `TicketImpact`
  - `TicketStatus`
  - `TicketType`
  - `EndUserFirstName`
  - `EndUserLastName`
  - `EndUserEmail`

### Update / resolve ticket
- `PUT /api/v3/tickets/{ticketId}`
- Editable fields documented in Swagger:
  - `TicketTitle`
  - `TicketStatus`
  - `TicketType`
  - `TicketPriority`
  - `TicketImpact`
  - `TechnicianContactID`
  - `TechnicianEmail`
- Resolve by sending `{"TicketStatus":"Resolved"}`.

### Add comment to ticket
- `POST /api/v3/tickets/{ticketId}/comments`
- Requires:
  - `CommentText`
  - and either `TechnicianCommentDetails` or `EnduserCommentDetails`
- Optional:
  - `CommentTimestampUtc`

#### Public technician comment
Use:
```json
{
  "CommentText": "...",
  "CommentTimestampUtc": "<utc timestamp>",
  "TechnicianCommentDetails": {
    "TechnicianId": <existing technician id>,
    "IsInternal": false,
    "TechnicianEmail": "<optional technician email>"
  }
}
```

#### Internal technician note
Use:
```json
{
  "CommentText": "...",
  "CommentTimestampUtc": "<utc timestamp>",
  "TechnicianCommentDetails": {
    "TechnicianId": <existing technician id>,
    "IsInternal": true,
    "TechnicianEmail": "<optional technician email>"
  }
}
```

#### End-user comment
Use:
```json
{
  "CommentText": "...",
  "CommentTimestampUtc": "<utc timestamp>",
  "EnduserCommentDetails": {
    "EnduserId": <existing end user id>,
    "EnduserEmail": "<optional end user email>"
  }
}
```

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

Get structured context for one ticket by `TicketID`:
```bash
python3 tools/atera/atera_tickets.py ticket-context <ticket_id> --items 25
```

List comments by `TicketID`:
```bash
python3 tools/atera/atera_tickets.py comments <ticket_id> --page 1 --items 25
```

Draft reply (testing aid only):
```bash
python3 tools/atera/atera_tickets.py draft-reply <ticket_id> --items 25
```

Dry-run a public technician comment by `TicketID`:
```bash
python3 tools/atera/atera_tickets.py comment-add <ticket_id> "text" --technician-id "$ATERA_TECHNICIAN_ID" --technician-email "$ATERA_TECHNICIAN_EMAIL" --dry-run
```

Add a public technician comment by `TicketID`:
```bash
python3 tools/atera/atera_tickets.py comment-add <ticket_id> "text" --technician-id "$ATERA_TECHNICIAN_ID" --technician-email "$ATERA_TECHNICIAN_EMAIL"
```

Add an internal note by `TicketID`:
```bash
python3 tools/atera/atera_tickets.py comment-add <ticket_id> "text" --technician-id "$ATERA_TECHNICIAN_ID" --technician-email "$ATERA_TECHNICIAN_EMAIL" --internal
```

Dry-run resolve by `TicketID`:
```bash
python3 tools/atera/atera_tickets.py resolve <ticket_id> --dry-run
```

Resolve by `TicketID`:
```bash
python3 tools/atera/atera_tickets.py resolve <ticket_id>
```

Update a ticket by `TicketID`:
```bash
python3 tools/atera/atera_tickets.py update <ticket_id> --status Pending --priority High
```

Add a ticket to the watch list:
```bash
python3 tools/atera/atera_tickets.py watch-add <ticket_id> --reason "likely high priority"
```

List watched tickets:
```bash
python3 tools/atera/atera_tickets.py watch-list
```

Remove a ticket from the watch list:
```bash
python3 tools/atera/atera_tickets.py watch-remove <ticket_id>
```

Urgent / watched alert check:
```bash
python3 tools/atera/atera_alerts.py
```

JSON urgent / watched alert check:
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
- Use `TicketID` for `get`, `ticket-context`, `comments`, `draft-reply`, `comment-add`, `update`, `resolve`, and watch-list actions.
- Treat `draft-reply` as a testing aid, not the primary decision engine.
- Use `ticket-context` as the main structured input to the model.
- Treat `comment-add`, `update`, and `resolve` as live actions when `--dry-run` is not used.
- In beta, always get Bob's approval before work, and again before posting the final message and resolving.
- Keep urgent checks read-only. Use alerts and watch checks to surface tickets for Bob review and Teams escalation.
