# Atera Ticket Helper

Current helper: `tools/atera/atera_tickets.py`

## Working commands

- `list [--status Pending]`
- `get <ticket_id>`
- `ticket-context <ticket_id> [--items 25]`
- `comments <ticket_id>`
- `draft-reply <ticket_id>`
- `comment-add <ticket_id> "text" --technician-id ... --technician-email ... --dry-run`
- `comment-add <ticket_id> "text" --technician-id ... --technician-email ...`
- `comment-add <ticket_id> "text" --technician-id ... --technician-email ... --internal`
- `comment-add <ticket_id> "text" --as-enduser --end-user-id ... [--end-user-email ...]`
- `update <ticket_id> --status ... --priority ... --dry-run`
- `update <ticket_id> --status ... --priority ...`
- `resolve <ticket_id> --dry-run`
- `resolve <ticket_id>`
- `watch-add <ticket_id> --reason ...`
- `watch-list`
- `watch-remove <ticket_id>`
- `triage`
- `high`
- `stale --days 7`
- `needs-response`
- `pending-user`
- `action-queue`

## Notes

- Preferred nanobot key path: `$NANOBOT_WORKSPACE/secrets/atera_api_key`.
- Default fallback key path: `~/.nanobot/workspace/secrets/atera_api_key`.
- Optional environment values:
  - `ATERA_TECHNICIAN_ID`
  - `ATERA_TECHNICIAN_EMAIL`
- Cloudflare may block the default Python client unless a normal `User-Agent` is sent.
- Status alone is not enough for queue triage; `waiting_on()` uses last end-user vs technician comment timestamps.
- Queue views now print both the human-facing `TicketNumber` and the API `TicketID` when both are available.
- Atera ticket records expose `EndUserID`, `EndUserEmail`, `EndUserFirstName`, and `EndUserLastName`; customer/site should not be treated as the opener/contact.
- Use `TicketID` for `get`, `ticket-context`, `comments`, `draft-reply`, `comment-add`, `update`, `resolve`, and watch-list actions.
- `comment-add`, `update`, and `resolve` are live actions unless `--dry-run` is used.
- Urgent checks are intentionally read-only.
- `draft-reply` is a testing aid. Long-term model workflows should prefer structured `ticket-context` plus explicit actions.

## Official v3 API task map

These are the official Swagger-backed mappings the helper should follow.

### Read ticket
- `GET /api/v3/tickets/{ticketId}`
- Returns fields such as `EndUserID`, `EndUserEmail`, `EndUserFirstName`, and `EndUserLastName`.

### Create ticket
- `POST /api/v3/tickets`
- Requires `EndUserID`, `TicketTitle`, and `Description`.

### Update / resolve ticket
- `PUT /api/v3/tickets/{ticketId}`
- Editable fields include:
  - `TicketTitle`
  - `TicketStatus`
  - `TicketType`
  - `TicketPriority`
  - `TicketImpact`
  - `TechnicianContactID`
  - `TechnicianEmail`
- Resolve using `{"TicketStatus":"Resolved"}`.

### Add comment
- `POST /api/v3/tickets/{ticketId}/comments`
- Requires `CommentText` and either `TechnicianCommentDetails` or `EnduserCommentDetails`.
- Optional `CommentTimestampUtc`.

Public technician comment example:
```json
{
  "CommentText": "done",
  "CommentTimestampUtc": "2026-03-29T05:39:44.745Z",
  "TechnicianCommentDetails": {
    "TechnicianId": 123,
    "IsInternal": false,
    "TechnicianEmail": "tech@example.com"
  }
}
```

Internal note example:
```json
{
  "CommentText": "internal note",
  "CommentTimestampUtc": "2026-03-29T05:39:44.745Z",
  "TechnicianCommentDetails": {
    "TechnicianId": 123,
    "IsInternal": true,
    "TechnicianEmail": "tech@example.com"
  }
}
```

End-user comment example:
```json
{
  "CommentText": "user update",
  "CommentTimestampUtc": "2026-03-29T05:39:44.745Z",
  "EnduserCommentDetails": {
    "EnduserId": 80,
    "EnduserEmail": "user@example.com"
  }
}
```

## Beta workflow

1. Read the ticket using `ticket-context`.
2. Decide whether the ticket is fully within autonomous scope.
3. If it is **not** safely autonomous, do nothing outward and leave it for Bob.
4. If it **is** safely autonomous, message Bob for approval **before doing any work**.
5. After work is completed, message Bob again with the exact end-user message you want to send and that you want to resolve the ticket.
6. Only after approval, use `comment-add` and `resolve`.

## Urgent / watched tickets

- If a ticket looks high priority, add it to the watch list.
- Use recurring checks (for example every 10 minutes via HEARTBEAT) while watched tickets remain active.
- Escalate watched/urgent changes to Bob in Teams.

## Suggested validation

1. Run `triage` to confirm API access.
2. Copy the `id:...` value from a queue view and use it with `ticket-context`.
3. Use `comment-add --dry-run`, `update --dry-run`, and `resolve --dry-run` before any live ticket change.
4. Use a low-risk test ticket before relying on live actions.
