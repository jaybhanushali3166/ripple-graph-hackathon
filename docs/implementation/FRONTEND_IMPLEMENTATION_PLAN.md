# Ripple — Jay's frontend implementation plan

Prepared October 17, 2026. Status: proposed execution plan; frontend implementation has not started. Owner: Jay. Planned implementation branch: `feat/jay-frontend`.

This expands [Jay's assignment](JAY_IMPLEMENTATION.md) into buildable tasks. The [shared contract](SHARED_CONTRACT.md) remains authoritative for API behavior, and the [team plan](../../TEAM_IMPLEMENTATION_PLAN.md) remains authoritative for ownership and integration gates. Estimates below are elapsed working time from kickoff, not commitments about completed work.

**Review revision R1:** apply the [accepted review changes](REVIEW_UPDATES.md) while preserving the selected light editorial direction. Pavan publishes kickoff examples before live integration. Baseline/revised forecasts retain non-nullable decision_id with an establishing Decision; `DEC-12` stays unchanged. The server owns effective_at at preview creation, shown read-only and distinct from future delivery date; no fixed 6 PM cutover or custom effective-time control. Conflict owners come from blocking components; missing/ambiguous ownership means verification is needed unless a confirmed conflict takes precedence. Display recorded downstream forecasts without claiming automatic replanning. Support impact/owner and decision-lineage prompts; defer expertise ranking and broad Q&A. Retain stale-version, expiry, and duplicate-save behavior. Cedar/Delta need real source records, and rehearsal must include another valid delivery date. R1 changes workflow requirements, not this plan's visual choices.

## 1. Outcome and scope

Build one desktop workspace where an engineering or account lead can see which customer promises a delivery change affects, inspect the source-backed explanation, and save a reviewed follow-up.

The complete interaction is:

```text
View commitments → paste decision → inspect preview → confirm
→ inspect changed impacts → open evidence → generate follow-up
→ review/edit → save reviewed draft → refresh and retrieve
```

Keep all four synthetic Harbor commitments visible initially. Acme and Birch become date conflicts after the canonical permissions update; Cedar and Delta remain useful controls. Label the workspace “Synthetic demo data.” A first-time viewer should understand the promise/dependency mismatch before opening the assistant.

Deliver a single workspace, a source drawer, and a decision-review dialog. A small contextual question input belongs inside the follow-up panel. Login, marketing pages, additional workspaces, and general company search are outside this build.

## 2. Selected design direction

Jay selected “Light editorial workspace — warm neutrals, crisp tables, restrained accents.” Use this direction for implementation. Interpret “non AI” as a request for a deliberately designed product rather than a generic generated dashboard. Exact color values, typography, and interaction details below remain proposals to demonstrate in the visual preview.

**Visual thesis:** make the customer's promised date and the dependency's forecast the strongest comparison on a warm, light workspace, using graphite text, a restrained ink-blue selection accent, compact spacing on a 4px base, flat bordered panels with small radii, and a system sans-serif with tabular date numerals.

**Interaction thesis:** selection and source access respond immediately; use 120–180ms color/opacity transitions and a short drawer entrance, keep scroll native, and avoid bounce, parallax, looping decoration, and animated graph rearrangement. Reduced motion removes drawer movement and change pulses.

**Allowed patterns:** fine panel dividers, restrained semantic status badges, tabular dates, directed evidence connectors, one brief highlight for a server-confirmed status change.

Specific choices that make the product feel considered:

- Use a shared row structure for commitments so customer, promise date, and status can be compared quickly.
- Put “Promised by” and “Dependency forecast” next to each other in the selected detail. Display server-provided reasons beneath them.
- Use red only for confirmed date conflicts, amber for verification needs, and neutral styling for “No detected date conflict.” Pair status text with an icon.
- Give the evidence chain the visual emphasis normally spent on decorative dashboard charts. Each relationship has its own source control.
- Use real people names and roles supplied by the API. Missing owners display “Owner needs verification.”
- Keep product text concrete: “Review decision,” “View source,” “Prepare follow-up,” and “Save reviewed draft.”
- Use a few CSS custom properties for palette, spacing, type, borders, focus, and motion. Keep this local to the app; do not build a reusable design-system package.

Before implementing the visual layer, show one representative workspace with a selected Acme commitment, a source drawer, and default/loading/error states. Use the selected light editorial direction; review its exact colors, typography, and interactions in that preview.

## 3. Design skills, plugins, and UI dependencies

Use tools to support explicit product decisions. A plugin does not establish design quality by itself.

| Tool or capability | Intended use | Readiness and scope |
| --- | --- | --- |
| Paint skill | Candidate for art direction, visual/interaction proposals, and visual audit | Entry instructions reviewed. Supporting `_jutsu` modules were not found in the inspected local skill directories; run its documented resolver before invoking the pipeline. Its full workflow is larger than this hackathon needs, so use it only if that scope is chosen. |
| Cast skill | Candidate for one focused interaction polish pass after live integration | Listed as available; instructions/modules still need checking before use. Only add motion that helps track selection or confirmed changes. |
| Figma plugin | Bring in a user-supplied reference or design file, if one becomes available | Listed as available to install, currently unconnected. Optional; no file/reference is currently supplied. |
| Radix Dialog | Implement the source drawer and decision dialog with accessible focus behavior | Proposed code dependency, not a connected plugin. Its [dialog documentation](https://www.radix-ui.com/primitives/docs/components/dialog) covers keyboard interaction and focus handling. Apply app-specific styling. |
| Lucide React | Supply a consistent small set of interface icons | Proposed code dependency, not a plugin. Use the [official React package](https://lucide.dev/guide/react/), with text labels for consequential actions. |

Do not block the frontend on plugin installation or third-party design accounts. If Paint's modules are unavailable, continue with a local visual proposal and manual design review; do not describe that as a completed Paint audit. No plugin or dependency was installed while preparing this plan.

## 4. Workspace layout

```text
┌────────────────────────────────────────────────────────────────────┐
│ Ripple / Harbor       Synthetic demo data       Review decision    │
├────────────────┬───────────────────────────────┬───────────────────┤
│ Commitments    │ Selected commitment           │ Follow-up         │
│                │ Customer + promised date      │ Grounded answer   │
│ Acme           │ Dependency forecast + owners  │ Citations         │
│ Birch          │                               │ Editable draft    │
│ Cedar          │ Evidence path                 │ Assignee          │
│ Delta          │ Customer → promise → work     │ Save reviewed     │
│                │ item → dependency chain       │ draft             │
│                │ Forecast history              │ Saved actions     │
└────────────────┴───────────────────────────────┴───────────────────┘
                        Source drawer overlays the right side on demand
```

Target the recording layout at 1440×900 first. Start with a 260px list, flexible evidence pane, and approximately 360px follow-up pane. Treat these as layout starting points, not fixed constraints. At 1024px, move follow-up below the evidence pane. At narrow widths, stack sections and use a vertical evidence path so content remains reachable; a separate mobile product is deferred.

The source drawer shows the stored title, type, timestamp, and body as plain text, with an exact quote highlighted when available. Edge payloads provide `source_id` without a quote: open the source normally for those edges, and highlight only when an actual matching quote was supplied by a citation. If a supplied quote is absent, show a visible verification warning rather than manufacturing a match. Closing returns focus to the triggering control.

An evidence path is a deterministic sequence of DOM nodes and connectors, not a force-directed graph. Read its nodes and edge directions directly from the response. Offer a path selector when several paths exist; preserve every returned path and expose completeness warnings beside the visualization.

## 5. Stack and file structure

Follow the agreed React + Vite + TypeScript stack. Vite provides an official [`react-ts` scaffold](https://vite.dev/guide/). Use plain CSS with app tokens, native `fetch`, React state/reducers, and the limited UI dependencies above. Check the runtime requirements of the chosen Vite release and pin working versions when scaffolding.

One route is sufficient. Introduce neither a global state package nor a graph rendering library initially. Keep network logic separate from rendering and keep each workflow's async state explicit.

```text
frontend/
  package.json / lockfile / index.html / vite.config.ts / tsconfig*.json
  src/
    main.tsx
    App.tsx
    api/
      types.ts                 # snake_case request/response DTOs
      client.ts                # /api, JSON/errors, AbortSignal
      impacts.ts               # impacts, source, forecast history
      decisions.ts             # immutable preview + confirm
      agent.ts
      actions.ts
    hooks/
      useWorkspace.ts          # selection, reads, evidence invalidation
      useDecisionReview.ts     # input/preview/confirmation states
      useFollowUp.ts           # impact/lineage prompts, edits, save/retry state
    components/
      WorkspaceHeader.tsx
      CommitmentList.tsx
      CommitmentDetail.tsx
      StatusBadge.tsx
      EvidencePath.tsx
      ForecastHistory.tsx
      SourceDrawer.tsx
      DecisionReviewDialog.tsx
      FollowUpPanel.tsx
      ToolTrace.tsx
      DraftEditor.tsx
      SavedActions.tsx
      InlineNotice.tsx
    lib/
      dates.ts                 # Asia/Kolkata formatting
    styles/
      tokens.css
      global.css
      workspace.css
    mocks/
      fixtures.ts              # baseline/changed/negative examples
      transport.ts             # explicit development-only transport
    tests/                     # critical workflow behavior only
docs/
  demo-script.md
```

`hooks/` and `lib/` are frontend-only extensions to Jay's ownership. Keep backend schemas/services, graph fixtures, Compose, and environment files with their existing owners. Record the chosen frontend port/proxy configuration with Pavan before scaffolding; `/api` is the browser-facing prefix.

## 6. API integration and state rules

Mirror the complete shared wire types in `api/types.ts`; preserve snake_case and treat `evidence_version` as opaque. Do not calculate authoritative impacts, infer owners, or reconstruct graph facts in the client.

| Operation | UI consumer | Success behavior |
| --- | --- | --- |
| `GET /api/impacts` | List, selected detail, completeness notices | Render all commitments and retain the selected ID if it still exists. |
| `GET /api/sources/{source_id}` | Source drawer | Display the stored body and validate supplied quote matches. |
| `GET /api/work-items/{work_item_id}/history` | Forecast history | Show accepted forecast entries and citations. No timeline slider is required. |
| `POST /api/decisions/preview` | Decision review | Render stored preview fields, warnings, expiry, and evidence version. |
| `POST /api/decisions/confirm` | Confirm button | Refetch impacts/history/actions; invalidate earlier generated drafts. |
| `POST /api/agent/run` | Contextual follow-up | Display answer, citations, tool trace, warnings, and editable drafts. |
| `POST /api/actions` | Save reviewed draft | Refetch server Actions; show persisted reviewed status. |
| `GET /api/actions?commitment_id=…` | Saved Actions | Fetch on initial selected commitment, selection changes, refresh, and save. |

Use explicit phases for mutations:

```text
Decision: editing → previewing → reviewing → confirming → confirmed
Draft:    idle → generating → reviewing/editing → saving → saved
```

Errors, expiry, and stale evidence are explicit branches out of these phases. A loading boolean alone is insufficient.

- Store preview ID, version, and expiry together. Editing either source text or title invalidates the preview and requires a new one. Confirmation sends only `preview_id`, `expected_version`, and `idempotency_key`.
- Render effective_at as read-only server preview time. Delivery/forecast dates remain future end-of-day values; neither the model nor the browser chooses the decision-effective time. A 422 review_required for a custom historical/future effective-time request retains the user's note and explains the supported live workflow.
- Generate an idempotency key once per logical submission and retain its exact payload for retry. After a network timeout, retry that payload/key. A deliberate new submission receives a new key. Freeze edits while a mutation's outcome is unresolved, or require the user to resolve/retry it first.
- Disable duplicate submission while pending. Do not optimistically invent confirmed decisions, revised impacts, or persisted Actions.
- On HTTP 409, inspect the error code. `stale_evidence` invalidates the preview/draft, refetches current evidence, and requires fresh review. `idempotency_conflict` reports the conflict and requires resolving the attempt; do not silently retry it as a new mutation. Neither error triggers automatic confirmation.
- On HTTP 410, require a fresh preview. On 422, retain user text and show the relevant field/review error. On 503, show graph unavailability. An AI partial response remains clearly labelled; empty drafts cannot appear as a completed follow-up.
- Abort obsolete reads and guard every completion with selection/request identity. Agent results and history must also match the selected commitment and current evidence version. Discard obsolete completions even when cancellation fails.
- Keep all versioned panels coherent. If a refresh reveals a new version, invalidate generated drafts and refresh the other versioned reads before enabling mutations. Preserve user-authored edits visibly as stale review text where useful, with saving disabled.
- Require assignee, nonempty body, citations, relevant decision IDs, and current evidence before enabling save. The server remains responsible for validation. Display saved Actions with their original version, and mark older ones “Needs re-review.”
- Show `completeness.warnings` and `truncated` beside results. Preserve the distinction between “Date conflict,” “Needs verification,” and “No detected date conflict.” A confirmed conflict can still carry missing-information warnings.
- For conflict results, display the server's blocking-component owner, not a feature owner inferred from a path. Multiple/missing owners render as verification work. Show baseline and revised establishing Decisions via history/source citations, and keep recorded feature dates separate from later dependency forecasts.
- Format wire timestamps with `Intl.DateTimeFormat` and `timeZone: 'Asia/Kolkata'`. Explain the end-of-day IST meaning for promise/forecast dates in review. Include the year in pasted demo notes; fixtures must not rely on ambiguous dates.
- Use explicit development mocks only when a local flag selects mock transport, with a visible mock-mode banner. Default to live mode; production builds cannot enable that transport. Live failures never fall through to mock success.

## 7. Build sequence and reviewable checkpoints

| Window | Implementation work | Checkpoint |
| --- | --- | --- |
| 0:00–0:30 | Confirm payload examples, ports/proxy, canonical note, IDs, and error shapes with Pavan. Show one representative layout in the selected light editorial direction. | No unresolved endpoint assumption blocks the shell. Detailed visual choices are recorded as approved or still proposed. |
| 0:30–2:00 | Scaffold app/client; add explicit baseline and changed mocks; build list, selected detail, evidence chain, source drawer, and review-panel shell. | A local mock build demonstrates all four commitments and navigable citations. Mock mode is obvious. |
| 2:00–4:00 | Connect real impacts, sources, history, and Action reads as available. Handle completeness and selected-request races. | Browser displays actual graph-backed paths and source text. If this fails, pause visual polish. |
| 4:00–5:00 | Connect preview/confirm, expiry, stable retries, and version invalidation. Refetch and highlight changed statuses. | Canonical update yields exactly Acme/Birch conflicts from server responses; Cedar/Delta remain visible. |
| 5:00–6:00 | Connect agent answer/trace, draft editing, validation, save, and retrieval. | A reviewed Action appears from a server refetch after save and page reload. |
| 6:00–8:00 | Verify stale/expired/unavailable/partial states, duplicate-click handling, keyboard behavior, and recording layout. Coordinate persistence/restart check with Pavan. | Full live flow and critical failure cases pass; restart preserves the saved Action. |
| 8:00–10:00 | Tighten typography, contrast, copy, and layout; add only useful motion. Write demo script and record the verified product. | Roughly three-minute walkthrough plus reproducible frontend startup/build instructions handed to Pavan. |

Make small implementation commits at runnable checkpoints: shell/mocks, live evidence, decision confirmation, reviewed Actions, and final verification. Creating this plan does not create those commits or branches.

## 8. Verification and definition of done

Automate a few high-value interactions using the frontend test runner selected during scaffolding. Avoid snapshot coverage for static panels.

1. A slow Acme response cannot overwrite Birch after the user changes selection; include late agent/history responses.
2. Editing a reviewed note invalidates its preview; timeout retries reuse the same mutation payload/key and repeated clicks produce one pending submission.
3. Stale evidence invalidates review and disables save/confirm until a fresh review; expiry requires a new preview.
4. Missing owner/evidence prevents saving, while a persisted Action from the server remains visible after remount; older evidence is marked for re-review.

Run TypeScript checks, production build, and these focused interaction checks. Confirm production cannot select development mocks. Browser checks must cover:

- Baseline four commitments → canonical update → exactly two conflicts. Inspect both an affected customer and an unaffected control.
- Rehearse a different valid delivery date through live preview/confirm and verify the returned statuses, without a fixed-time cutover. Test component-owner selection, missing-owner precedence, complete Cedar/Delta sources, and the decision-lineage question against source-backed baseline/revised Decisions.
- Click each edge/source citation, inspect an exact quote, switch paths, and inspect forecast history. Unknown source and quote mismatch have useful states.
- Generate a follow-up using the live agent, inspect tool trace and citations, edit, save, and reload. Coordinate an actual backend restart and retrieve the Action again; a component test does not prove persistence.
- Exercise graph outage, AI partial output, missing owner, stale evidence, expired preview, and network timeout using controlled dev/integration cases. No mock success appears in live mode.
- Keyboard through selection, decision review, drawer, and draft save. Verify Escape/close, focus return, visible focus, labels, and announced pending/error status.
- Check contrast with computed values, inspect at 1440×900 and 1024px width, and verify stacked content at 768px and 375px. Test 200% zoom and reduced motion.
- Verify a production build with the real `/api` deployment routing agreed with Pavan. Record any check that could not run as unverified.

Done means a new viewer understands the product, the live graph determines the visible outcome, evidence is inspectable, and a reviewed follow-up survives reload/restart. The handoff records actual check results and remaining limits, rather than claiming a tool or screenshot proved correctness.

## 9. First work package and scope cuts

The first implementation package is the React scaffold, typed API boundary, explicit baseline/changed development fixtures, and a complete static workspace with source navigation. It should establish the visual direction and expose integration assumptions before adding mutations.

Obtain from Pavan: agreed ports/proxy, exact route readiness, validation-error examples, source-not-found behavior, and Action status shape. Obtain from Ashwin: representative path/history responses and confirmation of the canonical baseline. Obtain from Abhijeet: canonical note with an explicit year and a representative partial agent result. These are coordination tasks; no message to a teammate has been sent by preparing this plan.

If time slips, cut optional motion, advanced filtering, a history slider, elaborate stale-state visuals, and plugin exploration first. Preserve readable history/source access for the two bounded question types, basic 409/410 handling, the ordered path, source drawer, preview/confirm review, honest errors, and durable reviewed Action. Expertise ranking, broad Q&A, and blog work are deferred. Follow the team plan for broader deployment/submission tradeoffs; a blog must not consume fix/submission buffer.
