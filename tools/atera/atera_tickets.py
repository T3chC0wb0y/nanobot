#!/usr/bin/env python3
import argparse
import html
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timezone
from urllib import request, parse, error

BASE_URL = os.environ.get('ATERA_BASE_URL', 'https://app.atera.com/api/v3').rstrip('/')


SIGNOFF_PATTERNS = [
    re.compile(r'^thanks[,!]*$', re.IGNORECASE),
    re.compile(r'^thank you[.!]*$', re.IGNORECASE),
    re.compile(r'^regards[,!]*$', re.IGNORECASE),
    re.compile(r'^best[,!]*$', re.IGNORECASE),
    re.compile(r'^sincerely[,!]*$', re.IGNORECASE),
]

QUOTED_PATTERNS = [
    re.compile(r'^from:\s', re.IGNORECASE),
    re.compile(r'^sent:\s', re.IGNORECASE),
    re.compile(r'^to:\s', re.IGNORECASE),
    re.compile(r'^subject:\s', re.IGNORECASE),
    re.compile(r'^on .+ wrote:\s*$', re.IGNORECASE),
]


def default_key_paths() -> list[Path]:
    workspace = os.environ.get('NANOBOT_WORKSPACE')
    paths: list[Path] = []
    if workspace:
        ws = Path(workspace).expanduser()
        paths.extend([
            ws / 'secrets' / 'atera_api_key',
            ws / '.secrets' / 'atera_api_key',
            ws / 'tools' / 'atera' / 'api_key',
        ])

    paths.extend([
        Path('~/.nanobot/workspace/secrets/atera_api_key').expanduser(),
        Path('~/.nanobot/workspace/.secrets/atera_api_key').expanduser(),
    ])
    return paths


def load_api_key():
    key = os.environ.get('ATERA_API_KEY')
    if key:
        return key.strip()

    key_file = os.environ.get('ATERA_API_KEY_FILE')
    if key_file and os.path.exists(key_file):
        with open(key_file, 'r', encoding='utf-8') as f:
            return f.read().strip()

    for path in default_key_paths():
        if path.exists():
            return path.read_text(encoding='utf-8').strip()

    return None


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except Exception:
        return None


def fmt_age(value):
    dt = parse_dt(value)
    if not dt:
        return '-'
    delta = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    hours = int(delta.total_seconds() // 3600)
    days = hours // 24
    if days:
        return f'{days}d'
    return f'{hours}h'


def waiting_on(ticket):
    end_ts = parse_dt(ticket.get('LastEndUserCommentTimestamp'))
    tech_ts = parse_dt(ticket.get('LastTechnicianCommentTimestamp'))
    if end_ts and (not tech_ts or end_ts > tech_ts):
        return 'us'
    if tech_ts and (not end_ts or tech_ts > end_ts):
        return 'them'
    if not tech_ts:
        return 'us'
    return '-'


def next_action(ticket):
    w = waiting_on(ticket)
    status = (ticket.get('TicketStatus') or '').lower()
    if w == 'us':
        return 'reply/work'
    if w == 'them' and status == 'pending':
        return 'wait/follow-up'
    if status == 'open':
        return 'work'
    return '-'


def clean_html_text(value):
    if not value:
        return ''
    text = html.unescape(str(value))
    text = re.sub(r'(?i)<br\s*/?>', '\n', text)
    text = re.sub(r'(?i)</p\s*>', '\n', text)
    text = re.sub(r'(?i)<p\b[^>]*>', '', text)
    text = re.sub(r'(?is)<style\b[^>]*>.*?</style>', ' ', text)
    text = re.sub(r'(?is)<script\b[^>]*>.*?</script>', ' ', text)
    text = re.sub(r'(?s)<[^>]+>', ' ', text)
    text = text.replace('\xa0', ' ')
    text = re.sub(r'\r\n?', '\n', text)
    return text.strip()


def normalize_space(value):
    return re.sub(r'\s+', ' ', value or '').strip()


def ticket_text(ticket):
    parts = [
        ticket.get('TicketTitle') or '',
        clean_html_text(ticket.get('FirstComment') or ''),
        clean_html_text(ticket.get('LastEndUserComment') or ''),
        clean_html_text(ticket.get('LastTechnicianComment') or ''),
    ]
    return ' '.join(parts).lower()


def t(ticket, field):
    value = ticket.get(field)
    if value is None:
        return ''
    return str(value)


def ticket_ref(ticket):
    ticket_number = t(ticket, 'TicketNumber')
    ticket_id = t(ticket, 'TicketID')
    if ticket_number and ticket_id and ticket_number != ticket_id:
        return f'#{ticket_number} (id:{ticket_id})'
    if ticket_number:
        return f'#{ticket_number}'
    if ticket_id:
        return f'id:{ticket_id}'
    return 'id:-'


def sort_key_recent(ticket):
    for field in ('LastEndUserCommentTimestamp', 'LastTechnicianCommentTimestamp', 'TicketCreatedDate'):
        dt = parse_dt(ticket.get(field))
        if dt:
            return dt
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def action_bucket(ticket):
    txt = ticket_text(ticket)
    wait = waiting_on(ticket)
    stale_days = (datetime.now(timezone.utc) - sort_key_recent(ticket).astimezone(timezone.utc)).days

    if wait == 'them':
        if stale_days >= 14:
            return 'close-cleanup'
        return 'waiting-on-user'

    session_keywords = {
        'book a support session', 'book a session', 'remote', 'log in', 'login', 'signed in',
        'computer', 'laptop', 'desktop', 'onedrive', 'sharepoint', 'outlook', 'adobe', 'indesign',
        'crashing', 'crash', 'not working', 'sync', 'printer', 'domain', 'install', 'setup'
    }
    if any(k in txt for k in session_keywords):
        return 'needs-session'

    return 'reply-now'


def request_json(path, params=None, method='GET', payload=None):
    api_key = load_api_key()
    if not api_key:
        raise RuntimeError('No API key found. Set ATERA_API_KEY or ATERA_API_KEY_FILE.')

    url = f"{BASE_URL}{path}"
    if params:
        url += '?' + parse.urlencode({k: v for k, v in params.items() if v is not None})

    data = None
    headers = {
        'Accept': 'application/json',
        'X-Api-Key': api_key,
        'User-Agent': 'Mozilla/5.0 (nanobot Atera Helper)',
    }
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(payload).encode('utf-8')

    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode('utf-8', errors='replace')
            return resp.status, body
    except error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return e.code, body


def fetch_tickets(status=None, page=1, items=25):
    params = {'page': page, 'itemsInPage': items, 'ticketStatus': status}
    status_code, body = request_json('/tickets', params=params)
    if status_code != 200:
        raise RuntimeError(f'HTTP {status_code}: {body[:300]}')
    data = json.loads(body) if body else {}
    return data.get('items') or [], data


def fetch_ticket(ticket_id):
    status, body = request_json(f'/tickets/{ticket_id}')
    if status != 200:
        raise RuntimeError(f'HTTP {status}: {body[:300]}')
    return json.loads(body) if body else {}


def fetch_comments(ticket_id, page=1, items=25):
    status, body = request_json(f'/tickets/{ticket_id}/comments', params={'page': page, 'itemsInPage': items})
    if status != 200:
        raise RuntimeError(f'HTTP {status}: {body[:300]}')
    data = json.loads(body) if body else {}
    return data.get('items') or data.get('Items') or data.get('comments') or []


def print_ticket_line(ticket):
    print(
        f"{ticket_ref(ticket)} | "
        f"{ticket.get('TicketStatus')} | {ticket.get('TicketPriority')} | "
        f"age {fmt_age(ticket.get('TicketCreatedDate'))} | "
        f"wait:{waiting_on(ticket)} | next:{next_action(ticket)} | "
        f"{ticket.get('CustomerName') or '-'} | {ticket.get('TicketTitle') or '-'}"
    )


def print_dry_run(action, ticket_id, payload):
    print(json.dumps({
        'dry_run': True,
        'action': action,
        'ticket_id': ticket_id,
        'payload': payload,
    }, indent=2, sort_keys=True))


def looks_like_bad_name(value):
    if not value:
        return True
    name = normalize_space(clean_html_text(value))
    if not name:
        return True
    if len(name) > 40:
        return True
    if any(token in name.lower() for token in ['<', '>', '@', 'http://', 'https://']):
        return True
    if re.search(r'\b(ticket|issue|support|service request|request)\b', name, re.IGNORECASE):
        return True
    if name.count('|') or name.count('/') > 1:
        return True
    return False


def title_case_name(value):
    words = []
    for part in normalize_space(value).split(' '):
        if not part:
            continue
        if re.fullmatch(r"[A-Z][a-z]+(?:[-'][A-Z][a-z]+)*", part):
            words.append(part)
        else:
            words.append(part[:1].upper() + part[1:].lower())
    return ' '.join(words).strip()


def extract_customer_name(ticket, comments):
    candidates = [
        ticket.get('ContactName'),
        ticket.get('EndUserName'),
        ticket.get('CustomerContactName'),
        ticket.get('RequesterName'),
        ticket.get('CustomerName'),
    ]
    for comment in reversed(comments):
        for key in ('EndUserName', 'ContactName', 'CustomerContactName', 'FromName', 'AuthorName', 'Name'):
            if key in comment:
                candidates.append(comment.get(key))

    for candidate in candidates:
        if looks_like_bad_name(candidate):
            continue
        cleaned = normalize_space(clean_html_text(candidate))
        cleaned = re.sub(r'\s*\([^)]*\)\s*', ' ', cleaned)
        cleaned = re.sub(r'\s*-\s*.+$', '', cleaned)
        cleaned = re.sub(r'\s*,\s*.+$', '', cleaned)
        cleaned = normalize_space(cleaned)
        if looks_like_bad_name(cleaned):
            continue
        return title_case_name(cleaned)
    return ''


def strip_signature_and_quotes(text):
    lines = [line.strip() for line in text.splitlines()]
    cleaned_lines = []
    for line in lines:
        if not line:
            if cleaned_lines and cleaned_lines[-1] != '':
                cleaned_lines.append('')
            continue
        if line.startswith('>'):
            break
        if any(pat.match(line) for pat in QUOTED_PATTERNS):
            break
        if line in {'--', '---', '___'}:
            break
        if any(pat.match(line) for pat in SIGNOFF_PATTERNS):
            break
        if re.fullmatch(r'[-_]{5,}', line):
            break
        cleaned_lines.append(line)

    while cleaned_lines and cleaned_lines[-1] == '':
        cleaned_lines.pop()
    return '\n'.join(cleaned_lines).strip()


def clean_comment_text(value):
    text = clean_html_text(value)
    text = strip_signature_and_quotes(text)
    text = re.sub(r'\b(?:cid:|image\d+\.)\S+', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def summarize_comment(text, limit=220):
    text = normalize_space(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(' ', 1)[0].strip()
    return (cut or text[:limit]).rstrip(',. ') + '...'


def latest_comment_text(ticket, comments):
    for field in ('LastEndUserComment', 'LastTechnicianComment', 'FirstComment'):
        value = clean_comment_text(ticket.get(field) or '')
        if value:
            return value
    for comment in reversed(comments):
        for key in ('CommentText', 'commentText', 'Text', 'text', 'Body', 'body'):
            value = clean_comment_text(comment.get(key) or '')
            if value:
                return value
    return ''


def draft_reply_text(ticket, comments):
    title = normalize_space(clean_html_text(ticket.get('TicketTitle') or '')) or 'this issue'
    customer = extract_customer_name(ticket, comments)
    wait = waiting_on(ticket)
    action = next_action(ticket)
    latest = summarize_comment(latest_comment_text(ticket, comments))

    opening = f"Hi {customer}," if customer else 'Hi,'
    lines = [opening, '']

    if wait == 'us':
        lines.append(f"Thanks for the update about {title}.")
        if latest:
            lines.append(f"I reviewed your latest note: \"{latest}\"")
        if action == 'reply/work':
            lines.append("We’re looking into it now and I’ll follow up with the next step shortly.")
        else:
            lines.append("I’m reviewing the next step now and will follow up shortly.")
    elif wait == 'them':
        lines.append(f"I’m following up on {title}.")
        if latest:
            lines.append(f"My last update was about: \"{latest}\"")
        lines.append("When you have a chance, please send the requested details or let me know whether the issue is still happening.")
    else:
        lines.append(f"I’m reviewing {title} and will follow up with the next step shortly.")
        if latest:
            lines.append(f"The latest note I have is: \"{latest}\"")

    lines.extend(['', 'Thank you,'])
    return '\n'.join(lines)


def cmd_list(args):
    params = {
        'page': args.page,
        'itemsInPage': args.items,
        'ticketStatus': args.status,
    }
    status, body = request_json('/tickets', params=params)
    print(f'HTTP {status}')
    if args.raw:
        print(body)
        return 0 if status == 200 else 1

    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        print(body)
        return 0 if status == 200 else 1

    items = data.get('items') or []
    print(f"count={len(items)} total={data.get('totalItemCount')}")
    for ticket in items[: args.limit]:
        print(
            f"{ticket_ref(ticket)} | "
            f"{ticket.get('TicketPriority')} | {ticket.get('TicketStatus')} | "
            f"{ticket.get('CustomerName') or '-'} | {ticket.get('TicketTitle') or '-'}"
        )
    return 0 if status == 200 else 1


def cmd_get(args):
    status, body = request_json(f'/tickets/{args.ticket_id}')
    print(f'HTTP {status}')
    print(body)
    return 0 if status == 200 else 1


def cmd_comments(args):
    status, body = request_json(f'/tickets/{args.ticket_id}/comments', params={'page': args.page, 'itemsInPage': args.items})
    print(f'HTTP {status}')
    print(body)
    return 0 if status == 200 else 1


def cmd_comment_add(args):
    payload = {'CommentText': args.text}
    if args.dry_run:
        print_dry_run('comment-add', args.ticket_id, payload)
        return 0

    status, body = request_json(f'/tickets/{args.ticket_id}/comments', method='POST', payload=payload)
    print(f'HTTP {status}')
    print(body)
    return 0 if status in (200, 201) else 1


def cmd_update(args):
    payload = {}
    if args.title:
        payload['TicketTitle'] = args.title
    if args.status:
        payload['TicketStatus'] = args.status
    if args.priority:
        payload['TicketPriority'] = args.priority
    if args.impact:
        payload['TicketImpact'] = args.impact
    if args.type:
        payload['TicketType'] = args.type
    if args.tech_id is not None:
        payload['TechnicianContactID'] = args.tech_id
    if args.tech_email:
        payload['TechnicianEmail'] = args.tech_email

    if not payload:
        raise RuntimeError('No update fields provided.')

    if args.dry_run:
        print_dry_run('update', args.ticket_id, payload)
        return 0

    status, body = request_json(f'/tickets/{args.ticket_id}', method='PUT', payload=payload)
    print(f'HTTP {status}')
    print(body)
    return 0 if status == 200 else 1


def cmd_draft_reply(args):
    ticket = fetch_ticket(args.ticket_id)
    comments = fetch_comments(args.ticket_id, page=1, items=args.items)
    print(f"ticket={ticket_ref(ticket)}")
    print(f"waiting_on={waiting_on(ticket)}")
    print(f"next_action={next_action(ticket)}")
    print()
    print(draft_reply_text(ticket, comments))
    return 0


def gather_active(statuses, items):
    tickets = []
    for st in statuses:
        found, _ = fetch_tickets(status=st, page=1, items=items)
        tickets.extend(found)
    return tickets


def cmd_triage(args):
    statuses = [s.strip() for s in args.statuses.split(',') if s.strip()]
    tickets = gather_active(statuses, args.items)
    tickets.sort(key=sort_key_recent, reverse=True)

    print(f'triage_count={len(tickets)} statuses={statuses}')
    for ticket in tickets[: args.limit]:
        print_ticket_line(ticket)
    return 0


def cmd_high(args):
    statuses = [s.strip() for s in args.statuses.split(',') if s.strip()]
    tickets = gather_active(statuses, args.items)
    tickets = [t for t in tickets if (t.get('TicketPriority') or '').lower() in {'high', 'urgent', 'critical'}]
    tickets.sort(key=sort_key_recent, reverse=True)
    print(f'high_count={len(tickets)} statuses={statuses}')
    for ticket in tickets[: args.limit]:
        print_ticket_line(ticket)
    return 0


def cmd_stale(args):
    statuses = [s.strip() for s in args.statuses.split(',') if s.strip()]
    tickets = gather_active(statuses, args.items)
    stale = []
    now = datetime.now(timezone.utc)
    for ticket in tickets:
        last_touch = sort_key_recent(ticket)
        age_days = (now - last_touch.astimezone(timezone.utc)).days
        if age_days >= args.days:
            stale.append((age_days, ticket))
    stale.sort(key=lambda x: x[0], reverse=True)
    print(f'stale_count={len(stale)} threshold_days={args.days} statuses={statuses}')
    for age_days, ticket in stale[: args.limit]:
        print(f'{age_days}d stale | ', end='')
        print_ticket_line(ticket)
    return 0


def cmd_needs_response(args):
    statuses = [s.strip() for s in args.statuses.split(',') if s.strip()]
    tickets = gather_active(statuses, args.items)
    tickets = [t for t in tickets if waiting_on(t) == 'us']
    tickets.sort(key=sort_key_recent, reverse=True)
    print(f'needs_response_count={len(tickets)} statuses={statuses}')
    for ticket in tickets[: args.limit]:
        print_ticket_line(ticket)
    return 0


def cmd_pending_user(args):
    statuses = [s.strip() for s in args.statuses.split(',') if s.strip()]
    tickets = gather_active(statuses, args.items)
    tickets = [t for t in tickets if waiting_on(t) == 'them']
    tickets.sort(key=sort_key_recent, reverse=True)
    print(f'pending_user_count={len(tickets)} statuses={statuses}')
    for ticket in tickets[: args.limit]:
        print_ticket_line(ticket)
    return 0


def cmd_action_queue(args):
    statuses = [s.strip() for s in args.statuses.split(',') if s.strip()]
    tickets = gather_active(statuses, args.items)
    buckets = {
        'reply-now': [],
        'needs-session': [],
        'waiting-on-user': [],
        'close-cleanup': [],
    }
    for ticket in tickets:
        buckets[action_bucket(ticket)].append(ticket)

    for name in buckets:
        buckets[name].sort(key=sort_key_recent, reverse=True)

    order = ['reply-now', 'needs-session', 'waiting-on-user', 'close-cleanup']
    for name in order:
        print(f'[{name}] count={len(buckets[name])}')
        for ticket in buckets[name][: args.limit_per_bucket]:
            print_ticket_line(ticket)
        print()
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description='Atera ticket helper',
        epilog='Queue views print TicketNumber and TicketID together when both are present. Detail, comments, draft-reply, update, and comment-add require TicketID.',
    )
    sub = p.add_subparsers(dest='cmd', required=True)

    p_list = sub.add_parser('list', help='List tickets')
    p_list.add_argument('--page', type=int, default=1)
    p_list.add_argument('--items', type=int, default=25)
    p_list.add_argument('--limit', type=int, default=10)
    p_list.add_argument('--status', help='Filter by status')
    p_list.add_argument('--raw', action='store_true')
    p_list.set_defaults(func=cmd_list)

    p_get = sub.add_parser('get', help='Get ticket by TicketID')
    p_get.add_argument('ticket_id', type=int, help='Atera TicketID, not TicketNumber')
    p_get.set_defaults(func=cmd_get)

    p_comments = sub.add_parser('comments', help='List comments for a ticket by TicketID')
    p_comments.add_argument('ticket_id', type=int, help='Atera TicketID, not TicketNumber')
    p_comments.add_argument('--page', type=int, default=1)
    p_comments.add_argument('--items', type=int, default=25)
    p_comments.set_defaults(func=cmd_comments)

    p_comment_add = sub.add_parser('comment-add', help='Add comment to a ticket by TicketID')
    p_comment_add.add_argument('ticket_id', type=int, help='Atera TicketID, not TicketNumber')
    p_comment_add.add_argument('text')
    p_comment_add.add_argument('--dry-run', action='store_true', help='Print the proposed comment payload without sending it')
    p_comment_add.set_defaults(func=cmd_comment_add)

    p_update = sub.add_parser('update', help='Update a ticket by TicketID')
    p_update.add_argument('ticket_id', type=int, help='Atera TicketID, not TicketNumber')
    p_update.add_argument('--title')
    p_update.add_argument('--status')
    p_update.add_argument('--priority')
    p_update.add_argument('--impact')
    p_update.add_argument('--type')
    p_update.add_argument('--tech-id', type=int)
    p_update.add_argument('--tech-email')
    p_update.add_argument('--dry-run', action='store_true', help='Print the proposed update payload without sending it')
    p_update.set_defaults(func=cmd_update)

    p_draft_reply = sub.add_parser('draft-reply', help='Draft a reply for a ticket by TicketID')
    p_draft_reply.add_argument('ticket_id', type=int, help='Atera TicketID, not TicketNumber')
    p_draft_reply.add_argument('--items', type=int, default=25, help='How many recent comments to inspect when drafting')
    p_draft_reply.set_defaults(func=cmd_draft_reply)

    p_triage = sub.add_parser('triage', help='Queue view for active tickets')
    p_triage.add_argument('--statuses', default='Open,Pending')
    p_triage.add_argument('--items', type=int, default=25)
    p_triage.add_argument('--limit', type=int, default=20)
    p_triage.set_defaults(func=cmd_triage)

    p_high = sub.add_parser('high', help='High priority active tickets')
    p_high.add_argument('--statuses', default='Open,Pending')
    p_high.add_argument('--items', type=int, default=50)
    p_high.add_argument('--limit', type=int, default=20)
    p_high.set_defaults(func=cmd_high)

    p_stale = sub.add_parser('stale', help='Stale active tickets')
    p_stale.add_argument('--statuses', default='Open,Pending')
    p_stale.add_argument('--items', type=int, default=50)
    p_stale.add_argument('--days', type=int, default=7)
    p_stale.add_argument('--limit', type=int, default=20)
    p_stale.set_defaults(func=cmd_stale)

    p_needs = sub.add_parser('needs-response', help='Tickets waiting on you')
    p_needs.add_argument('--statuses', default='Open,Pending')
    p_needs.add_argument('--items', type=int, default=50)
    p_needs.add_argument('--limit', type=int, default=20)
    p_needs.set_defaults(func=cmd_needs_response)

    p_pending_user = sub.add_parser('pending-user', help='Tickets waiting on the user')
    p_pending_user.add_argument('--statuses', default='Open,Pending')
    p_pending_user.add_argument('--items', type=int, default=50)
    p_pending_user.add_argument('--limit', type=int, default=20)
    p_pending_user.set_defaults(func=cmd_pending_user)

    p_action_queue = sub.add_parser('action-queue', help='Bucket tickets by best next action')
    p_action_queue.add_argument('--statuses', default='Open,Pending')
    p_action_queue.add_argument('--items', type=int, default=50)
    p_action_queue.add_argument('--limit-per-bucket', type=int, default=5)
    p_action_queue.set_defaults(func=cmd_action_queue)

    return p


if __name__ == '__main__':
    parser = build_parser()
    args = parser.parse_args()
    try:
        sys.exit(args.func(args))
    except Exception as e:
        print(f'ERROR: {e}', file=sys.stderr)
        sys.exit(2)
