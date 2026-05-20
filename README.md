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

**Bootstrap + initial persistence layer implemented.** The app starts,
loads config (JSON file or defaults), configures console logging,
opens a SQLite database with WAL mode, applies the initial schema,
and handles Ctrl+C gracefully (closes the DB on shutdown).

Three core repositories are wired and ready:

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

The plan for StreamArch is to reuse the cookie system from StreamCapQT/StreamCapOrigin because it already works well in production.

Recommended browser extension for exporting compatible cookies:

- **Export cookie JSON file for Puppeteer**
- https://chromewebstore.google.com/detail/export-cookie-json-file-for-puppeteer/nmckokihipjgplolmcmjakknndddifde?hl=es&utm_source=ext_sidebar

See the detailed guide in:

- [`docs/cookies-import.md`](docs/cookies-import.md)
