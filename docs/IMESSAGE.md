# iMessage (remote only)

This branch adds a built-in `imessage` channel for **remote-only** iMessage integration using Photon HTTP transport.

Intentionally not included: local macOS database polling and AppleScript send logic.

The goal on this branch is a clean, reviewable remote agent implementation.

## Scope

Current scope on this branch:

- remote-only iMessage transport via Photon-compatible HTTP endpoints
- inbound polling of recent messages
- outbound text replies
- outbound media/file sending
- inbound attachment download
- optional typing indicators
- optional tapback reaction lifecycle for "working" and "done"
- message deduplication and startup history seeding
- group-chat allow/ignore policy
- optional reply-to-message support

## Configuration

Example config:

```json
{
  "channels": {
    "imessage": {
      "enabled": true,
      "serverUrl": "https://xxxxx.imsgd.photon.codes",
      "apiKey": "your-api-key",
      "allowFrom": ["*"],
      "pollInterval": 2.0,
      "groupPolicy": "open",
      "replyToMessage": false,
      "enableTypingIndicator": true,
      "reactTapback": "love",
      "doneTapback": "like",
      "reactToInbound": true,
      "seedHistoryOnStart": true
    }
  }
}
```

## Field reference

- `enabled` enables the iMessage channel
- `serverUrl` is the Photon server or Photon Kit URL
- `apiKey` authenticates to the Photon transport
- `allowFrom` is the normal channel allowlist
- `proxy` is an optional HTTP proxy
- `pollInterval` is the polling interval in seconds
- `groupPolicy` is `open` or `ignore`
- `replyToMessage` adds reply metadata on the first outbound message when available
- `enableTypingIndicator` sends typing start/stop events while the bot is responding
- `reactTapback` applies a working tapback to inbound messages
- `doneTapback` is optional and is applied after a successful response
- `reactToInbound` controls whether inbound messages get a working tapback
- `seedHistoryOnStart` marks existing recent messages as seen on startup

## Reaction lifecycle

When enabled:
1. inbound message arrives
2. the channel applies `reactTapback` to indicate the bot is working
3. the channel sends typing indicator while composing/sending the reply
4 . after successful send, the channel removes `reactTapback`
5. if `doneTapback` is set, the channel applies it as the final status marker

## Photon URL handling

If `serverUrl` points to a Photon Kit host like `https://xxxxx.imsgd.photon.codes`, the channel automatically routes requests through the shared Photon proxy endpoint and encodes the bearer token in the format expected by the upstream transport.

## Notes

- This branch is intentionally remote-only.
- No local macOS support is included.
- The implementation is meant to stay small, focused, and easy to review.
- If more features are added later, they should land as narrow follow-up commits with matching tests.
