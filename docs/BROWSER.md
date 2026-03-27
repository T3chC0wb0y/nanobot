# Browser Tools (MVP)

Nanobot now includes a narrow browser MVP for authenticated/local browsing workflows.

## Included tools

- `browser_open` — open a URL in the local browser session
- `browser_text` — extract visible text from the current page or a URL
- `browser_screenshot` — save a screenshot of the current page or a URL

This MVP is intentionally small. It does **not** yet include click/type automation, element refs, or attach-to-existing-browser support.

## Configuration

Add a `tools.browser` section to `~/.nanobot/config.json`:

```json
{
  "tools": {
    "browser": {
      "enabled": true,
      "headless": true,
      "userDataDir": "~/.nanobot/browser",
      "viewportWidth": 1440,
      "viewportHeight": 900,
      "navigationTimeoutMs": 30000,
      "maxTextChars": 20000
    }
  }
}
```

Optional fields:

- `executablePath` — explicit Chrome/Chromium executable path
- `headless` — set `false` if you want a visible browser window

## Install requirements

Python dependency:

```bash
uv sync
```

Browser binary:

```bash
uv run playwright install chromium
```

## Notes

- Browser tools are disabled by default.
- Browser URLs go through the same SSRF-safe URL validation used by `web_fetch`.
- Text returned by `browser_text` is marked as untrusted external/browser content.
- The browser session uses a persistent profile directory from `userDataDir`, so manual logins can persist across runs.
