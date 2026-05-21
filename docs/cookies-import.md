# Cookie system in StreamArch

## What it does

Some platforms need valid cookies to:

- resolve streams correctly,
- avoid blocks or restrictions,
- access content that fails or responds poorly without a session.

The cookie subsystem stores cookies **per platform** in local JSON files,
converts them on import to a ``name=value; ...`` string, and exposes a
simple service to get, set, import, and list cookies — all with atomic
save semantics and no external dependencies.

## Storage format

Cookies live in ``data/cookies/{platform}.json`` (configurable via
``cookies_dir`` in the JSON config). Each file looks like:

```json
{
  "cookies": [
    {
      "name": "sessionid",
      "value": "abc123",
      "domain": ".twitch.tv",
      "path": "/",
      "http_only": true,
      "secure": true
    }
  ],
  "cookie_string": "sessionid=abc123; ...",
  "updated_at": "2026-05-21T12:00:00+00:00"
}
```

The ``cookie_string`` field is pre-computed at write time so consumers
(resolvers, API handlers, CLI tools) can read it without iterating.

## Service API

The application facade ``CookieService`` (wired in the DI container as
``container.cookie_service``) exposes:

| Method | Description |
|--------|-------------|
| ``get_cookie_string(platform)`` → ``str`` | Get `name=value; ...` for a platform (``""`` if none) |
| ``import_cookies(platform, json_path)`` → ``int`` | Import from Puppeteer-style JSON, returns count |
| ``set_cookie(platform, name, value)`` | Set or update a single cookie, preserving others |
| ``list_platforms()`` → ``list[str]`` | Platforms that have stored cookies |

### Example usage

```python
from app.infrastructure.cookies.cookie_storage import CookieStore
from app.application.services.cookie_service import CookieService

store = CookieStore("./data/cookies")
service = CookieService(store)

# Import
count = service.import_cookies("twitch", "twitch_cookies.json")
print(f"Imported {count} cookies")

# Read
cookie_string = service.get_cookie_string("twitch")
# → "sessionid=abc123; persistent=xyz789; login_token=tok_42"

# Set one
service.set_cookie("youtube", "SESSION", "xyz")
```

## Import format

The importer accepts the JSON format produced by the Chrome extension
*Export cookie JSON file for Puppeteer*:

```json
[
  {
    "name": "sessionid",
    "value": "abc123",
    "domain": ".tiktok.com",
    "path": "/",
    "httpOnly": true,
    "secure": true
  }
]
```

On import the subsystem preserves all six fields (name, value, domain,
path, httpOnly, secure) and builds the cookie string automatically.

## Architecture

```
infrastructure/cookies/cookie_storage.py   ← CookieStore, CookieEntry
application/services/cookie_service.py     ← CookieService (facade)
bootstrap/container.py                     ← cookie_service wired here
bootstrap/startup.py                       ← CookieStore initialized from config
```

- The store lives in infrastructure because it manages file I/O.
- The service lives in application because it provides the use-case-level
  API to handlers and resolvers.
- REST endpoints expose cookie operations to external consumers (see
  `app/interfaces/api/routes.py` — the ``/api/v1/cookies/*`` routes).
- No UI and no platform-specific resolver integration yet.

## Security notes

### 1. Cookies are credentials
They represent an authenticated session. Do not share them or commit them.

### 2. Keep them out of Git
The ``.gitignore`` already excludes ``data/``, ``cookies.json``, and
``config/cookies.json``.

### 3. They expire
Even after a successful import, cookies may become invalid over time.

### 4. Export from the right domain
Cookies from the wrong domain will not help the platform resolver.
