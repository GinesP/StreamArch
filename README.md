# StreamArch

Stream monitoring and recording core engine — Python backend for scheduling, prediction, live detection, and recording of livestreams.

## Repository structure

```
app/                    # Core application package
├── domain/             # Business entities, value objects, rules, events
├── application/        # Use cases (commands/queries), services, DTOs, orchestrators
├── infrastructure/     # Persistence, ffmpeg, resolvers, scheduler, config, metrics
├── interfaces/         # REST API, WebSocket, presenters, mappers
├── bootstrap/          # DI container, startup, shutdown wiring
└── main.py             # Entry point

tests/                  # Test suites
├── unit/               # Domain logic tests
├── integration/        # Infrastructure integration tests
└── contract/           # API contract tests

docs/                   # Architecture documentation
```

## Current status

**Bootstrap + initial persistence layer + REST API slice implemented.**
The app starts, loads config (JSON file or defaults), configures console
logging, opens a SQLite database with WAL mode, applies the initial schema,
starts the REST API server, and handles Ctrl+C gracefully (shuts down
API server, closes the DB).

### REST API

A minimal stdlib HTTP server exposes the following endpoints (no external
framework required):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/streams` | List all streams with current monitoring state |
| `POST` | `/api/v1/streams` | Create a new stream target |
| `PATCH` | `/api/v1/streams/{stream_id}` | Update stream target fields |
| `POST` | `/api/v1/streams/{stream_id}/disable-monitoring` | Stop monitoring a stream |
| `POST` | `/api/v1/streams/{stream_id}/enable-monitoring` | Start monitoring a stream |
| `POST` | `/api/v1/streams/{stream_id}/favorite` | Mark stream as favourite |
| `DELETE` | `/api/v1/streams/{stream_id}/favorite` | Unmark stream as favourite |
| `GET` | `/api/v1/dashboard/state` | Aggregate dashboard state |
| `GET` | `/api/v1/recordings` | List recording sessions |
| `GET` | `/api/v1/cookies` | List platforms with stored cookies |
| `GET` | `/api/v1/cookies/{platform}` | Get cookie string and status for a platform |
| `POST` | `/api/v1/cookies/import` | Import cookies from a Puppeteer-style JSON file path |
| `POST` | `/api/v1/cookies/{platform}` | Set or update a single cookie for a platform |

The server listens on `127.0.0.1:8899` by default (configurable via
`api_host` / `api_port` in the JSON config or `config.example.json`).

### Repositories

| Repository | Operations |
|-----------|------------|
| `StreamTargetRepository` | save (upsert), get by id, list all |
| `MonitoringSnapshotRepository` | save (upsert), get by target id, list all |
| `RecordingSessionRepository` | save (upsert), get by id, list by target |

## Architecture docs

All architecture decisions are documented in `docs/`:

- [`docs/streamarch-general-architecture-draft.md`](docs/streamarch-general-architecture-draft.md) — High-level vision, components, and principles
- [`docs/core-modules-map.md`](docs/core-modules-map.md) — Detailed module structure and layer responsibilities
- [`docs/data-model-initial.md`](docs/data-model-initial.md) — Domain entities and SQLite schema
- [`docs/api-ws-contracts-initial.md`](docs/api-ws-contracts-initial.md) — REST and WebSocket contracts
- [`docs/architecture-initial-scheduler.md`](docs/architecture-initial-scheduler.md) — Scheduler and prediction engine design
- [`docs/streamcaporigin-preserve-refactor-drop.md`](docs/streamcaporigin-preserve-refactor-drop.md) — Migration decisions from StreamCapOrigin
- [`docs/cookies-import.md`](docs/cookies-import.md) — Cookie export/import guidance and operational notes

## Layers

| Layer | Responsibility |
|-------|---------------|
| `domain/` | Business rules, entities, value objects, state machines |
| `application/` | Use cases, coordination, DTOs |
| `infrastructure/` | Persistence, ffmpeg, resolvers, scheduler infrastructure |
| `interfaces/` | REST, WebSocket, presentation |
| `bootstrap/` | Wiring, startup, shutdown |

## Development

```bash
python -m app.main                            # Run with default config
python -m app.main --config config.example.json  # Run with custom config
```

## Runtime setup notes

Anything needed to run or operate StreamArch must be documented here or in `docs/`.

### Configuration file

An example runtime config exists at:

```text
config.example.json
```

You can launch the app with it using:

```bash
python -m app.main --config config.example.json
```

### Cookies

Some platforms may require valid cookies for reliable stream resolution.

The project reuses the cookie approach proven in StreamCapQT/StreamCapOrigin:
platform-keyed storage, JSON import from browser exports, atomic persistence,
and a framework-agnostic access layer.

**Cookie storage path**: `data/cookies/{platform}.json` (configurable via
`cookies_dir` in the JSON config).

**Currently implemented** — a minimal, stdlib-only cookie subsystem:

| Operation | Description |
|-----------|-------------|
| `import_cookies` | Import a Puppeteer-style JSON export for a platform |
| `set_cookie` | Set or update a single cookie for a platform |
| `get_cookie_string` | Get `name=value; ...` string for a platform |
| `list_platforms` | List platforms that have stored cookies |

See the detailed guide in:

- [`docs/cookies-import.md`](docs/cookies-import.md)

Recommended browser extension for exporting compatible cookies:

- **Export cookie JSON file for Puppeteer**
- https://chromewebstore.google.com/detail/export-cookie-json-file-for-puppeteer/nmckokihipjgplolmcmjakknndddifde?hl=es&utm_source=ext_sidebar
