# Ripple — Jay's frontend implementation plan

Prepared October 17, 2026. Status: frontend modules implemented and checked locally; live backend integration pending. Owner: Jay. Implementation branch: `feat/jay-frontend`. See the [module/task checklist](FRONTEND_TASKS.md) and [frontend run instructions](../../frontend/README.md) for current progress and verification limits.

This expands [Jay's assignment](JAY_IMPLEMENTATION.md) into buildable tasks. The [shared contract](SHARED_CONTRACT.md) remains authoritative for API behavior, and the [team plan](../../TEAM_IMPLEMENTATION_PLAN.md) remains authoritative for ownership and integration gates. Estimates below are elapsed working time from kickoff, not commitments about completed work.

**Review revision R1:** apply the [accepted review changes](REVIEW_UPDATES.md) while preserving the selected light editorial direction. Pavan publishes kickoff examples before live integration. Baseline/revised forecasts retain non-nullable decision_id with an establishing Decision; `DEC-12` stays unchanged. The server owns effective_at at preview creation, shown read-only and distinct from future delivery date; no fixed 6 PM cutover or custom effective-time control. Conflict owners come from blocking components; missing/ambiguous ownership means verification is needed unless a confirmed conflict takes precedence. Display recorded downstream forecasts without claiming automatic replanning. Support impact/owner and decision-lineage prompts; defer expertise ranking and broad Q&A. Retain stale-version, expiry, and duplicate-save behavior. Cedar/Delta need real source records, and rehearsal must include another valid delivery date. R1 changes workflow requirements, not this plan's visual choices.

**Frontend reconciliation with R1, October 17, 2026:** the tasks below now specify feature-forecast retrieval through existing history reads, owner semantics in canonical UI fixtures, two explicit agent prompts, server-timed review, and reset/replay behavior. Endpoint paths and wire shapes remain those in the shared contract; this update adds no API fields. The earlier interactive design sample illustrates the visual direction only and needs the corrections in section 4 before it can serve as a workflow reference.

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
- Put “Promised by,” “Recorded feature forecast,” and “Blocking dependency forecast” together in the selected detail. Let these wrap at smaller widths. When there is no blocker, label dependency dates as recorded forecasts rather than conflicts. Display server-provided reasons beneath them, with “Replanning needed” for a confirmed feature/dependency discrepancy; never replace the feature date with the dependency date.
- Use red only for confirmed date conflicts, amber for verification needs, and neutral styling for “No detected date conflict.” Pair status text with an icon.
- Give the evidence chain the visual emphasis normally spent on decorative dashboard charts. Each relationship has its own source control.
- Use synthetic people names and roles supplied by the API. Label the engineering owner “Blocking work owner” for a date conflict and “Required work owner” otherwise. Missing/ambiguous owners display “Owner needs verification” with the server's warning; do not pick a candidate in the browser.
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
│                │ Promise + feature forecast    │ Two prompt choices│
│ Acme           │ Dependency forecast + owners  │ Answer + citations│
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

**Forecast and decision detail:** fetch the required root WorkItem's accepted history as well as each selected blocking WorkItem's history. Use the selected impact response's `as_of` to display the recorded forecast whose interval contains that time (`valid_from <= as_of`, and `valid_to` absent or greater than `as_of`). This selects a recorded fact for display; the server still determines impact status. Identify required roots from the returned requirement edges using the exact relation values agreed at kickoff. If multiple roots exist, show each rather than selecting one arbitrarily. A missing/mismatched history response shows a loading or verification notice and never a guessed forecast.

For a selected forecast, expose its non-null `decision_id`, accepted interval, and exact supporting citations. Keep the forecast-to-establishing-Decision relationship intact when showing baseline and revised records; do not attribute every forecast to the latest Decision on the same WorkItem. Source access and the lineage prompt use the existing history/evidence/agent flow, without a new public Decision endpoint.

**Follow-up prompts:** provide “Which promises are affected, and who owns the follow-up?” and “Why did the permissions forecast change?” as contextual prompt buttons using `POST /api/agent/run` with the current `expected_version` and selected commitment where applicable. Keep their scope visible beside the input. Both display answer, citations, tool trace, and warnings. A lineage answer may be complete without drafts; reveal an editor only for a returned draft, with a separate choice between returned internal/customer drafts. Preserve the returned assignee per draft; never copy the engineering owner's ID into a customer-update draft.

**Canonical UI fixtures:** mirror the server examples and these R1 expectations. These are assertions for development/verification, not a production lookup table.

| Commitment | Baseline engineering owner | After the canonical update | Account owner |
| --- | --- | --- | --- |
| Acme SSO | Lena (`person_lena`), required SSO root | Date conflict; Priya (`person_priya`), blocking permissions work | Maya (`person_maya`) |
| Birch audit | Omar (`person_omar`), required audit root | Date conflict; Priya (`person_priya`), blocking permissions work | Nisha (`person_nisha`) |
| Cedar export | Eli (`person_eli`), required export root | No detected date conflict; Eli remains owner | Leo (`person_leo`) |
| Delta SSO | Lena (`person_lena`), required SSO root | No detected date conflict; Lena remains owner even though permissions changed | Noah (`person_noah`) |

Include source-backed handoffs and plans for Cedar/Delta, plus each baseline forecast's establishing Decision. Separate negative fixtures cover missing/ambiguous owners: without a confirmed blocker show `needs_verification`; with a confirmed blocker retain `date_conflict` and the ownership warning. Different or unresolved blocking owners produce a null engineering owner rather than a selected first owner.

**Earlier sample corrections before implementation:** remove its fixed 6 PM effective time, use the canonical explicit-year note, render effective time from `proposal.effective_at`, replace illustrative missing-owner placeholders with the canonical owners above, add the recorded feature forecast and decision lineage, and include both prompt choices. Its local “save” interaction remains a visual demonstration; production save/retrieval must use the Action API.

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
      impacts.ts               # impacts, source, root/blocker forecast history
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
      CommitmentDetail.tsx     # promise, recorded feature and dependency dates
      StatusBadge.tsx
      EvidencePath.tsx
      ForecastHistory.tsx      # establishing decision + interval + citations
      SourceDrawer.tsx
      DecisionReviewDialog.tsx
      FollowUpPanel.tsx        # impact/owner and decision-lineage prompts
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

Mirror Pavan's exact published models and JSON examples in `api/types.ts`; preserve snake_case and treat `evidence_version` as opaque. Layout scaffolding can start before that handoff, but typed integration fixtures must not invent competing fields. In particular, `Impact` and `PathNode` contain no feature-forecast property: consume existing history reads. `preview_created_at` is server-side orchestration input; the public preview exposes its value as `proposal.effective_at`, so add no client DTO field for it. Keep blocker/history `decision_id` non-nullable and keep canonical `DEC-12` unchanged. Do not calculate authoritative impacts, infer owners, or reconstruct graph facts in the client.

| Operation | UI consumer | Success behavior |
| --- | --- | --- |
| `GET /api/impacts` | List, selected detail, completeness notices | Render all commitments and retain the selected ID if it still exists. |
| `GET /api/sources/{source_id}` | Source drawer | Display the stored body and validate supplied quote matches. |
| `GET /api/work-items/{work_item_id}/history` | Feature/dependency date comparison and forecast history | Load histories for required roots and selected blockers, deduplicate reads by ID, and display establishing Decisions/citations at the impact `as_of`. No timeline slider is required. |
| `POST /api/decisions/preview` | Decision review | Render component, delivery date, read-only `proposal.effective_at`, owner, superseded Decision, exact quote, warnings, expiry, and evidence version. |
| `POST /api/decisions/confirm` | Confirm button | Refetch impacts/history/actions; invalidate earlier generated drafts. |
| `POST /api/agent/run` | Both contextual question types | Display answer, citations, tool trace, warnings, and returned drafts. Complete lineage answers do not require a draft. |
| `POST /api/actions` | Save reviewed draft | Refetch server Actions; show persisted reviewed status. |
| `GET /api/actions?commitment_id=…` | Saved Actions | Fetch on initial selected commitment, selection changes, refresh, and save. |

Use explicit phases for mutations:

```text
Decision: editing → previewing → reviewing → confirming → confirmed
Draft:    idle → generating → reviewing/editing → saving → saved
```

Errors, expiry, and stale evidence are explicit branches out of these phases. A loading boolean alone is insufficient.

- Store preview ID, version, and expiry together. Editing either source text or title invalidates the preview and requires a new one. Confirmation sends only `preview_id`, `expected_version`, and `idempotency_key`.
- Render `proposal.effective_at` as read-only server preview time. Delivery/forecast dates use the end-of-day IST convention and may be future dates; neither the model nor the browser chooses the decision-effective time. A 422 `review_required` for a custom historical/future effective-time request retains the user's note and explains the supported live workflow. A non-forward cutover also requires fresh review. Preview time preceding confirmation is valid; do not reject it as backdated based on the browser clock.
- Generate an idempotency key once per logical submission and retain its exact payload for retry. After a network timeout, retry that payload/key. A deliberate new submission receives a new key. Freeze edits while a mutation's outcome is unresolved, or require the user to resolve/retry it first.
- An identical completed retry in the same dataset may succeed even after its original preview expired or evidence advanced. Accept the replayed result, then refetch current impacts/history/Actions instead of rolling the workspace back to the returned historical version. Preserve the Action's original evidence version for re-review. Server reset creates a new dataset: old requests must return stale evidence rather than replay into it. On reset or an incompatible version refresh, clear obsolete preview/draft/read state, require fresh review, and never reuse the previous attempt as a new submission. Do not parse the opaque version or infer dataset identity from its text.
- Disable duplicate submission while pending. Do not optimistically invent confirmed decisions, revised impacts, or persisted Actions.
- On HTTP 409, inspect the error code. `stale_evidence` invalidates the preview/draft, refetches current evidence, and requires fresh review. `idempotency_conflict` reports the conflict and requires resolving the attempt; do not silently retry it as a new mutation. Neither error triggers automatic confirmation.
- On HTTP 410, require a fresh preview. On 422, retain user text and show the relevant field/review error. On 503, show graph unavailability. On 502 `ai_unavailable`, retain the selected context and user text and offer a deliberate retry. An AI partial response remains clearly labelled; render any useful answer/citations and warnings, but never fabricate a missing draft. Complete lineage answers with no drafts remain valid answers.
- Abort obsolete reads and guard every completion with selection/request identity. Agent results and history must also match the selected commitment and current evidence version. Discard obsolete completions even when cancellation fails.
- Keep all versioned panels coherent. If a refresh reveals a new version, invalidate generated drafts and refresh the other versioned reads before enabling mutations. Preserve user-authored edits visibly as stale review text where useful, with saving disabled.
- Require assignee, nonempty body, citations, relevant decision IDs, and current evidence before enabling save. The server remains responsible for validation. Display saved Actions with their original version, and mark older ones “Needs re-review.”
- Show `completeness.warnings` and `truncated` beside results. Preserve the distinction between “Date conflict,” “Needs verification,” and “No detected date conflict.” A confirmed conflict can still carry missing-information warnings.
- For conflict results, display the server's unique owner across all blocking WorkItems, not a feature owner inferred from a path. If blockers have different owners or any ownership is unresolved, the server returns null plus a warning. With no confirmed blocker, display the server's required-root owner. Account ownership is independent. Show baseline and revised establishing Decisions via history/source citations, and keep recorded feature dates separate from later dependency forecasts.
- Format wire timestamps with `Intl.DateTimeFormat` and `timeZone: 'Asia/Kolkata'`. Explain the end-of-day IST meaning for promise/forecast dates in review. Include the year in pasted demo notes; fixtures must not rely on ambiguous dates.
- Use explicit development mocks only when a local flag selects mock transport, with a visible mock-mode banner. Default to live mode; production builds cannot enable that transport. Live failures never fall through to mock success.

## 7. Build sequence and reviewable checkpoints

| Window | Implementation work | Checkpoint |
| --- | --- | --- |
| 0:00–0:30 | Consume exact kickoff models and JSON examples, agree ports/proxy and requirement-edge values, and confirm the canonical note/owner fixtures. Show the representative light editorial layout. | Scaffolding can start; typed integration uses the published contract examples. Detailed visual choices are recorded as approved or still proposed. |
| 0:30–2:00 | Scaffold app/client; add baseline/changed/negative fixtures; build list, all three date comparisons, evidence/source navigation, and both prompt controls. | A local mock build shows all four commitments, correct root/blocker owners, establishing Decisions, and navigable control sources. Mock mode is obvious. |
| 2:00–4:00 | Connect real impacts, sources, root/blocker histories, and Action reads. Handle completeness, version alignment, and selected-request races. | Browser displays graph-backed paths, recorded feature forecasts, dependency discrepancies, and source text. If this fails, pause visual polish. |
| 4:00–5:00 | Connect server-timed preview/confirm, expiry, stable retries, and version invalidation. Refetch and highlight changed statuses. | Immediate after-confirmation reads show exactly Acme/Birch conflicts; no fixed clock-time dependency. |
| 5:00–6:00 | Connect both agent question types, answer/trace, returned draft selection/editing, validation, save, and retrieval. | A source-backed lineage answer works; a reviewed Action appears from a server refetch after save and reload. |
| 6:00–8:00 | Verify stale/expired/unavailable/partial states, duplicate-click handling, keyboard behavior, and recording layout. Coordinate persistence/restart check with Pavan. | Full live flow and critical failure cases pass; restart preserves the saved Action. |
| 8:00–10:00 | Tighten typography, contrast, copy, and layout; add only useful motion. Write demo script and record the verified product. | Roughly three-minute walkthrough plus reproducible frontend startup/build instructions handed to Pavan. |

Make small implementation commits at runnable checkpoints: shell/mocks, live evidence, decision confirmation, reviewed Actions, and final verification. Creating this plan does not create those commits or branches.

## 8. Verification and definition of done

Automate a few high-value interactions using the frontend test runner selected during scaffolding. Avoid snapshot coverage for static panels.

1. A slow Acme response cannot overwrite Birch after the user changes selection; include late agent/history responses.
2. Editing a reviewed note invalidates its preview; timeout retries reuse the same mutation payload/key and repeated clicks produce one pending submission.
3. Stale evidence invalidates review and disables save/confirm until a fresh review; expiry requires a new preview.
4. Missing owner/evidence prevents saving, while a persisted Action from the server remains visible after remount; older evidence is marked for re-review.
5. Server-provided root/blocker owners and missing-owner status precedence render correctly; feature history uses the matching interval/version without replacing a feature forecast with a blocker date.
6. A lineage answer with no drafts renders as an answer with citations; no invented editor or saveable Action appears. Historical/future effective-time rejection retains the note, and a valid preview timestamp earlier than confirmation remains acceptable.

Run TypeScript checks, production build, and these focused interaction checks. Confirm production cannot select development mocks. Browser checks must cover:

- Baseline four commitments → canonical update → exactly two conflicts. Inspect both an affected customer and an unaffected control.
- Rehearse the exact explicit-year canonical note from the shared contract and another valid delivery date through live preview/confirm. Check the returned statuses rather than assuming the alternate date has the same affected customers. Use a reset or a valid forward review as appropriate; no fixed-time cutover is required.
- Verify the owner table above against server payloads, including Delta retaining Lena after the permissions update. Exercise mixed/unresolved blocking owners and missing account ownership with their status/warning precedence.
- Display the recorded feature forecast alongside the later dependency and explain that replanning is needed; no client-recalculated delivery date is shown. Verify the baseline/revised establishing Decision, including `DEC-12`, and its actual source in the lineage answer. Cedar/Delta source clicks must also work.
- Click each edge/source citation, inspect an exact quote, switch paths, and inspect forecast history. Unknown source and quote mismatch have useful states.
- Generate a follow-up using the live agent, inspect tool trace and citations, edit, save, and reload. Coordinate an actual backend restart and retrieve the Action again; a component test does not prove persistence.
- Exercise graph outage, AI partial output, missing owner, stale evidence, expired preview, and network timeout using controlled dev/integration cases. No mock success appears in live mode.
- Verify a completed same-payload retry after preview expiry returns the original success without duplication in the same dataset. After controlled demo reset, an old pending submission yields stale evidence, old UI review state is invalidated, and the next attempt uses a fresh preview/key. Coordinate these integration cases with Pavan; client tests alone do not establish replay correctness.
- Keyboard through selection, decision review, drawer, and draft save. Verify Escape/close, focus return, visible focus, labels, and announced pending/error status.
- Check contrast with computed values, inspect at 1440×900 and 1024px width, and verify stacked content at 768px and 375px. Test 200% zoom and reduced motion.
- Verify a production build with the real `/api` deployment routing agreed with Pavan. Record any check that could not run as unverified.
- In `docs/demo-script.md`, show the live update, the feature/dependency discrepancy, source-backed decision lineage, and a saved Action. Include Ashwin/Pavan's observed edge-removal proof in the recording or linked verification notes; do not implement arbitrary graph-edit controls to demonstrate it.

Done means a new viewer understands the product, the live graph determines the visible outcome, evidence is inspectable, and a reviewed follow-up survives reload/restart. The handoff records actual check results and remaining limits, rather than claiming a tool or screenshot proved correctness.

## 9. First work package and scope cuts

The first implementation package is the React scaffold, typed API boundary based on kickoff examples, explicit baseline/changed development fixtures with R1 owners/provenance, and a complete static workspace with source navigation and the three date comparisons. It should establish the visual direction and expose integration assumptions before adding mutations.

Obtain from Pavan: exact published models and JSON examples for baseline/changed impacts, history, preview/confirm, complete/partial agent runs, saved Actions, and 409/410 errors, plus ports/proxy, route readiness, validation/source-not-found behavior, and requirement-edge relation values. Obtain from Ashwin: source-backed root/blocker histories and the canonical owner/baseline fixtures. Obtain from Abhijeet: the canonical explicit-year note and representative impact/owner, lineage-only, and partial results. Layout scaffolding need not wait, but do not create competing API definitions. These are coordination tasks; no message to a teammate has been sent by preparing this plan.

If time slips, cut optional motion, advanced filtering, a history slider, elaborate stale-state visuals, and plugin exploration first. Preserve readable history/source access for the two bounded question types, basic 409/410 handling, the ordered path, source drawer, preview/confirm review, honest errors, and durable reviewed Action. Expertise ranking, broad Q&A, and blog work are deferred. Follow the team plan for broader deployment/submission tradeoffs; a blog must not consume fix/submission buffer.
