# Ripple frontend

The approved light editorial workspace, implemented as small React/TypeScript modules. Uses the [shared contract R1](../docs/implementation/SHARED_CONTRACT.md). Track modules and integration work in [frontend tasks](../docs/implementation/FRONTEND_TASKS.md).

## Run locally

Use Node **24.15+ LTS** (verified with 24.18.0) or Node 26+. Dependencies are pinned in `package.json` and `package-lock.json`.

```sh
cd frontend
npm ci
npm run dev:demo
```

Open the printed local URL, normally `http://127.0.0.1:5173`. The development banner identifies scripted fixtures. The default fixture is the baseline; use **Review decision → Use the synthetic sample note → Preview decision → Confirm reviewed update** to explore the change, or select an explicit development fixture. Acme/Birch become date conflicts. Delta/Cedar remain controls with source records and the correct owners.

Development answers and decision previews are scripted examples, not live extraction or graph reasoning. Development Actions live only in browser memory and reset on reload or fixture change. The demo deliberately accepts only the canonical note; a different delivery date requires the live backend.

## Connect the live API

```sh
npm run dev
```

Live mode is the default. Requests go to `/api`; Vite proxies them to `http://127.0.0.1:8000`. That port is a provisional local default pending Pavan's handoff. To change it, copy `.env.example` to `.env.local`, set `API_PROXY_TARGET`, and restart Vite. Do not put secrets in `VITE_*` variables.

There is no backend implementation in this checkout yet. A failed live request displays an error and never switches to fixtures. Types currently mirror the written contract; validate them against Pavan's actual schemas and kickoff JSON before claiming integration.

Production hosting must route `/api` to the backend on the same origin (or supply an equivalent reverse proxy). Vite's development proxy is not production infrastructure.

## Checks and production build

```sh
npm run typecheck
npm test
npm run build
npm run preview
```

Tests cover late reads, stable mutation replay payloads, duplicate clicks, immutable preview edits, stale/expired review, missing owners, coherent history, lineage-only answers, stored Action versions, and explicit live failures. Production builds exclude development fixture imports, including when built with `--mode demo`.

## Module map

- `src/api/`: snake_case wire types, `/api` transport, error mapping, endpoint functions.
- `src/hooks/`: selection-safe reads, workspace refresh, immutable mutation attempts/retries.
- `src/components/`: workspace regions, evidence/history, source drawer, decision review, follow-up/Actions.
- `src/lib/`: IST dates, recorded forecast interval selection, requirement-root lookup, synthetic sample note.
- `src/styles/`: app tokens and responsive editorial layout.
- `src/mocks/`: explicit development-only scenarios and transport.
- `src/tests/`: focused behavior checks; these do not prove backend semantics or durability.

The browser displays the required feature's recorded forecast alongside a blocking dependency; it does not recalculate delivery dates or authoritative impacts. Engineering/account owners come from the API. An Action is a reviewed stored draft, never a sent message.

## Integration still required

Validate exact DTOs/relation values, endpoint behavior, controlled reset, and proxy configuration with Pavan. Run live graph-backed reads, real extraction/agent calls, alternate-date rehearsal, mutation replay/version checks, and Action retrieval after a backend restart. Obtain the graph/edge-removal proof from Ashwin/Pavan. See [demo script](../docs/demo-script.md).
