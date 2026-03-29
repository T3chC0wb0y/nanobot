# Atera Ticket Helper

Current helper: `tools/atera/atera_tickets.py`

## Working commands

- `list [--status Pending]`
- `get <ticket_id>`
- `comments <ticket_id>`
- `draft-reply <ticket_id>`
- `comment-add <ticket_id> "text" --dry-run`
- `comment-add <ticket_id> "text"`
- `update <ticket_id> --status ... --priority ... --dry-run`
- `update <ticket_id> --status ... --priority ...`
- `triage`
- `high`
- `stale --days 7`
- `needs-response`
- `pending-user`
- `action-queue`

## Notes

- Preferred nanobot key path: `$NANOBOT_WORKSPACE/secrets/atera_api_key`.
- Default fallback key path: `~/.nanobot/workspace/secrets/atera_api_key`.
- Cloudflare may block the default Python client unless a normal `User-Agent` is sent.
- Status alone is not enough for queue triage; `waiting_on()` uses last end-user vs technician comment timestamps.
- Queue views now print both the human-facing `TicketNumber` and the API `TicketID` when both are available.
- Use `TicketID` for `get`, `comments`, `draft-reply`, `comment-add`, and `update`.
- Bob is currently the only technician, so `mine` is not especially useful.
- Booking link/signature behavior should be handled deliberately if comment posting is expanded later.
- `comment-add` and `update` are live actions unless `--dry-run` is used.
- Urgent checks are intentionally read-only for beta.

## Suggested validation

1. Run `triage` to confirm API access.
2. Copy the `id:...` value from a queue view and use it with `get`.
3. Use `draft-reply` to generate a proposed response for a low-risk test ticket.
4. Use `comment-add --dry-run` or `update --dry-run` before any live ticket change.
5. Use a test ticket before relying on live `comment-add` or `update` in production.
