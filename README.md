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

**Initial skeleton.** The package structure is in place with placeholder modules.
No business logic has been implemented yet.

## Architecture docs

All architecture decisions are documented in `docs/`:

- [`docs/streamarch-general-architecture-draft.md`](docs/streamarch-general-architecture-draft.md) — High-level vision, components, and principles
- [`docs/core-modules-map.md`](docs/core-modules-map.md) — Detailed module structure and layer responsibilities
- [`docs/data-model-initial.md`](docs/data-model-initial.md) — Domain entities and SQLite schema
- [`docs/api-ws-contracts-initial.md`](docs/api-ws-contracts-initial.md) — REST and WebSocket contracts
- [`docs/architecture-initial-scheduler.md`](docs/architecture-initial-scheduler.md) — Scheduler and prediction engine design
- [`docs/streamcaporigin-preserve-refactor-drop.md`](docs/streamcaporigin-preserve-refactor-drop.md) — Migration decisions from StreamCapOrigin

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
python -m app.main         # Run the core (stub)
```
