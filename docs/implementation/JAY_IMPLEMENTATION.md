# Jay — frontend and demo experience

You own the frontend, as requested. Your task is to make the value visible: a changed engineering decision reveals affected customer promises, and a user can inspect the evidence and review a follow-up. Pavan owns API integration services; Ashwin owns graph behavior; Abhijeet owns AI extraction and drafting.

Read the [team sequence](../../TEAM_IMPLEMENTATION_PLAN.md) and [shared contract](SHARED_CONTRACT.md). Branch: `feat/jay-frontend`.

Use the [detailed frontend implementation plan](FRONTEND_IMPLEMENTATION_PLAN.md) for the proposed visual direction, plugin/tool choices, component structure, API states, and build checkpoints.

**Review revision R1 — apply before integration**

- Use Pavan's kickoff JSON examples and exact types. decision_id stays non-nullable for baseline/revised forecasts; `DEC-12` keeps its current ID.
- Show effective_at as read-only server preview time, separate from delivery date. Offer no historical/future effective-time input, and do not hardcode a 6 PM change.
- For conflicts, engineering_owner is the blocking component's owner; otherwise it is the required root owner. Null/ambiguous owners need visible warnings. Missing ownership means needs_verification unless date_conflict already takes precedence.
- Display the recorded feature forecast alongside its late dependency; the product detects inconsistency without automatically recalculating schedules.
- Offer two contextual question prompts: affected promises/owners and “Why did this forecast change?” Show the establishing Decision and its source through existing evidence/history views.
- Preserve stale-version rejection, basic 410 expiry handling, and duplicate-save protection. Elaborate stale-state visuals are optional; safe review behavior is required.
- Include Cedar/Delta controls with their real source records, rehearse a different valid delivery date, and show the graph/edge-removal proof in the recording or linked verification notes. Defer expertise ranking, broad Q&A, and side-prize work.

See the [review disposition](REVIEW_UPDATES.md). The existing visual direction and frontend ownership are unchanged.

**Files you own**

```text
frontend/package.json and its lockfile
frontend/index.html
frontend/vite.config.ts
frontend/tsconfig*.json
frontend/src/main.tsx
frontend/src/App.tsx
frontend/src/api/*
frontend/src/components/*
frontend/src/styles/*
frontend/src/mocks/*
frontend/Dockerfile if needed
frontend tests/checks
docs/demo-script.md
```

Choose React + Vite + TypeScript with a small existing styling approach. Avoid a design-system build. You own frontend package/lockfile changes; ask Pavan for backend endpoint/schema changes rather than editing his files.

**First thirty minutes**

Confirm R1 API shapes, enum values, server-owned effective time, component-owner semantics, port/proxy setup, and canonical customer IDs with Pavan. Consume his example payloads rather than inventing fields. Sketch one desktop workspace with four regions: commitment list, selected impact/evidence, source drawer, and action review. Agree the explicit-year live note and baseline/changed states with Ashwin and Abhijeet.

The screen should initially explain the company context and show the four commitments. Lead with useful content rather than an empty chat input. Label all company data as synthetic.

**Hours 0:30–2:00: build against explicit mocks**

1. Scaffold the app and a single typed API client matching snake_case wire fields. Use `/api` through the agreed development proxy.
2. Build the commitments list with `date_conflict`, `needs_verification`, and `no_detected_conflict` states. Use readable labels and icons as well as color.
3. Build a selected-commitment pane containing promise date, blocker forecast, engineering/account owners, and an ordered evidence path.
4. Build a source drawer that shows stored source body and highlights the exact cited quote.
5. Add decision-input and review panels plus an action-draft editor with clear placeholder/dev states.

Use mock data only behind an explicit local-development flag or test harness. Do not ship a failed-live-call fallback to mocks. Keep API calls in `src/api/`; keep rendering separate from fetch logic so replacing mocks is quick.

**Hours 2:00–4:00: real impacts and source navigation**

Replace impact/source mocks with Pavan's real routes as soon as available. The hour-four gate is your browser showing actual FalkorDB-derived paths and source text.

Use a deterministic ordered layout for a selected evidence path: Customer → Commitment → required WorkItem → dependencies. A small SVG or normal positioned DOM is sufficient. Give every edge a clickable source indicator. Prefer a readable four- or five-node path over a force-directed graph cloud. If multiple paths exist, let the user select a path and retain all returned evidence.

Show missing/ambiguous owners as verification work. Surface `completeness.warnings` and `truncated`; do not imply every dependency was checked if the server says otherwise. Format dates with `Asia/Kolkata` and preserve the shared end-of-day meaning.

**Hours 4:00–6:00: complete the live workflow**

Wire the sequence:

1. Paste a note and call preview. Show extracted component, future delivery date, read-only server preview time as effective time, owner, superseded decision, exact source quote, and warnings. Do not offer custom historical/future decision-effective times.
2. Confirm only the server-stored preview using preview_id, expected_version, and one stable idempotency key for that confirmation attempt. Editing the note creates a new preview.
3. On success, refetch impacts and selected history; do not calculate authoritative affected customers in the browser.
4. Make the newly flagged Acme/Birch cards easy to notice while retaining Cedar/Delta as controls. A brief subtle highlight is enough.
5. Run the agent for the selected commitment; show answer, citations, structured tool trace, and editable internal/customer drafts. Add a second contextual prompt for decision lineage using the same agent/history/evidence views.
6. Save the reviewed draft through the Action API with its evidence version and idempotency key. Use “Save reviewed draft” wording; never imply sending.
7. Fetch saved Actions from the server after save and on page load, so refresh demonstrates persistence.

Prevent older network responses overwriting a newer selection/version, for example with AbortController/request IDs. On 409, invalidate the preview/draft and require fresh review against refetched data. Do not automatically confirm after a stale error. On 410, ask for a new preview. Retry the same payload with the same idempotency key; a deliberate new submission gets a new key.

**Hours 6:00–8:00: states and walkthrough**

Handle loading, no selected commitment, graph unavailable, partial AI output, invalid input, missing source, missing owner, expired preview, stale evidence, duplicate-click prevention, and action-save failure. Drafts require an owner and evidence before saving. Display warnings next to the affected content, not only in a toast.

Verify server-provided component-owner selection, missing-owner status precedence, complete Cedar/Delta sources, and non-null baseline decision lineage. Show the recorded feature forecast and dependency conflict without implying automatic replanning. Rehearse a different valid delivery date and immediate after-confirmation refresh without a fixed clock-time dependency.

Refresh after saving and verify the saved Action still appears from the backend. Preserve its original evidence version and mark older Actions for re-review after a new decision. Never store the authoritative graph or saved Action solely in browser state/localStorage.

Walk through the live flow with the team on the exact laptop/browser used for recording. Verify source clicks, keyboard-accessible controls, readable contrast, and a working desktop layout at the recording resolution. Add only meaningful client checks for stale-response handling or critical review interactions; avoid spending the deadline on snapshot coverage.

**Hours 8:00–10:00: presentation and submission**

Write `docs/demo-script.md` and record an approximately three-minute walkthrough:

- Explain the promise/dependency mismatch in twenty seconds.
- Show the synthetic source records and initial state.
- Paste the note, inspect its preview, and confirm.
- Show two affected customers plus an unaffected control.
- Click the evidence path and revised forecast source.
- Show agent tools, owners, citations, and a follow-up draft.
- Briefly answer the decision-lineage question using the establishing Decision/source; include the edge-removal proof in the video or linked verification notes.
- Save a reviewed Action and refresh.
- Close with the actual graph/query and verification evidence supplied by Ashwin/Pavan.

A direct recording of the functioning product comes first. Add optional animation or video tooling only if it saves time after the workflow is verified. Keep basic stale/expired feedback and verification ahead of visual flourishes, expertise questions, or blog work. Help Pavan verify the final repository, setup/deployment, and video links before submission.

Your definition of done: a new viewer understands the problem, sees a live source-backed change, can inspect why each customer is affected, and can save/retrieve a reviewed follow-up. The shipped UI uses real API results and communicates incomplete evidence honestly.
