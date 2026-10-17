# Frontend implementation tasks

Branch: `feat/jay-frontend`. Implements the approved light editorial sample with [R1 contract behavior](SHARED_CONTRACT.md). Tasks are small modules within this checkout, not separate agent assignments.

| Task | Module | Acceptance | Status |
| --- | --- | --- | --- |
| FE-01 | Foundation: React/Vite, app tokens, wire types, API boundary | Buildable app; live mode by default; explicit development demo mode | Implemented; live DTO handoff pending |
| FE-02 | Workspace: list, selection, dates and owner semantics | Four canonical commitments; keyboard access; responsive layout | Implemented and checked with development fixtures |
| FE-03 | Evidence: paths, source drawer, accepted history | Exact quote highlighting; root/dependency forecasts; establishing Decisions | Implemented; live provenance verification pending |
| FE-04 | Decision review | Paste → immutable preview → confirm; server time; retry/expiry/stale handling | Implemented; live extraction/mutation checks pending |
| FE-05 | Follow-up: agent and reviewed Actions | Both prompts, tool trace, draft editing, versioned save and retrieval | Implemented; live agent/durability checks pending |
| FE-06 | Verification and handoff | Focused tests, production build, browser checks, integration notes | Local checks complete; team integration pending |

Backend models, kickoff JSON examples, and live endpoints are not present in this checkout at the start of this work. Type definitions mirror only the published written contract and remain subject to validation against Pavan's actual handoff. Development fixtures do not establish graph/extraction correctness or backend persistence.

## Observed local checks — October 17, 2026

- TypeScript check and production build pass using Node 24.18.0.
- 19 tests pass across seven files: request races, immutable mutation retries, duplicate submission, preview invalidation/stale/expiry, lineage-only answers, ownership/evidence save gates, retaining reviewed text after validation errors, original Action versions, and live API failures.
- Chromium walkthrough passes: baseline → preview → confirm → evidence → lineage → edited draft → save → API refetch. Fixtures verify Delta's unaffected status/root owner, missing-owner save prevention, and labelled partial output.
- Layout has no horizontal overflow at 1440, 1024, 768, 375, and 320px. Browser page-error list is empty. Source quote highlighting, keyboard containment, Escape, and focus return pass. Reduced-motion media disables the drawer animation.
- Computed text contrast passes 4.5:1 for body, muted, primary-button, conflict, warning, and no-conflict text. Ratios range from 5.01:1 to 13.86:1 for the checked pairs.
- Production JavaScript contains none of the development fixture markers. Fixture imports are guarded by `import.meta.env.DEV` as well as the explicit demo flag. A production browser check with an HTTP 503 graph response shows the real error and no sample commitments.

Live graph/model behavior, backend restart persistence, another valid delivery date, overlapping confirmations, and the graph edge-removal proof remain **unverified** until the backend handoff. No deployment or external message sending was performed.

Run instructions: [frontend README](../../frontend/README.md). Recording flow: [demo script](../demo-script.md).

## PR #2 re-review fixes — October 17, 2026

- Keep the automatic Action-version refresh guard in `App`, outside the grid that unmounts during a reload. Persistent disagreement refreshes once per displayed evidence version, then remains visible with saving disabled.
- Resolve uncertain confirmations and Action saves by replaying their exact stored payload and idempotency key. A changed version or an older Action with matching text does not establish success. Only the mutation endpoint's successful result marks the operation complete.
- Closing an uncertain decision review preserves its pending attempt and lets it be reopened. Explicit abandonment requires a duplicate-risk acknowledgement and is unavailable during an in-flight request. Stale refreshes wait for unresolved mutations, preserving their retry keys.
- Highlight only transitions into `date_conflict`; clear on refresh and expire on a timer independent of impact reads.
- Protect edited drafts during selection, detail/header refresh, fixture changes, and stale refreshes. If a stale refresh is declined, retain the text while disabling stale submissions. Explain wrong-commitment draft routing explicitly.
- Validation: 41 tests across nine files pass, including actual App/grid remount regressions, repeated unknown-outcome checks, close/reopen replay, pending-request protection, and highlight expiry/resolution. TypeScript and production build pass. Live backend replay/durability verification remains pending.
