# Ripple — accepted review changes, revision R1

Updated October 17, 2026, following [Ashwin's review](../../REVIEW.md) and Jay's instruction to apply the review decisions. This is the current disposition of that review. The original review remains historical; not every expansion it suggests is in scope. The [shared contract](SHARED_CONTRACT.md) specifies behavior; individual plans assign implementation. Application work and kickoff handoffs are still pending.

| Review point | Decision | Responsible developer |
| --- | --- | --- |
| Forecast has no establishing decision | Add `Decision -ESTABLISHES-> Forecast`; seed source-backed baseline decisions and preserve non-nullable `decision_id` | Ashwin; Pavan validates DTOs; Abhijeet/Jay consume |
| Effective/backdated times ambiguous | Live effective_at is server preview time, never model-selected or fixed 6 PM. Defer custom historical/future decision-effective times; test history with separate fixtures | Pavan supplies/validates; Ashwin cuts over; Abhijeet does not infer; Jay displays read-only |
| Engineering owner ambiguous | Use unique blocking-component owner for conflicts; required root owner otherwise. Multiple/missing owners return null and warnings | Ashwin computes; Pavan validates; Abhijeet routes; Jay renders |
| Missing ownership/status unclear | Missing or ambiguous ownership means needs_verification unless a confirmed date_conflict takes precedence; retain the warning | All four |
| Operational record shapes absent | Document and implement GraphState and durable RequestRecord in FalkorDB; reset changes dataset identity | Ashwin and Pavan |
| `DEC-12` naming differs | Keep canonical `DEC-12`; no style-only migration | All four |
| Cedar/Delta provenance incomplete | Explicitly seed both handoffs, export plan, owners, forecasts, and sources; no invented no-conflict controls | Ashwin |
| Downstream forecasts stay unchanged | Accepted MVP limit. Check every dependency and display the recorded feature forecast alongside its conflict; no auto-replanning | All four |
| Product may appear hand-wired | Use realistic source bodies, demonstrate live extraction, and rehearse another valid delivery date. Describe deterministic seed mappings honestly | Ashwin, Abhijeet, Jay; Pavan verifies end-to-end |
| Add broad company-brain questions | Keep two supported types: affected promises/owners and decision lineage. Defer unrestricted Q&A and expertise ranking | Abhijeet and Jay |
| Remove invisible correctness work | Retain version/replay/expiry basics and one overlapping-confirmation check. Defer elaborate visuals, broad CI, and load testing | Ashwin, Pavan, Jay |
| Local paths and personal phrasing | Remove machine-specific skill path from product plan; neutralise team ownership label | Documentation update |
| Extra track/blog | No new build scope; assess track eligibility against completed behavior. Blog only after submission-critical work, never at the expense of buffer | Team |

**Chronology remains parallel**

1. First thirty minutes: Pavan and Ashwin publish exact typed boundaries and example responses; Abhijeet/Jay check their consumers against them. Scaffolds can start immediately.
2. By hour four: live graph reads reach the browser, with complete source provenance and explicit owner semantics.
3. By hour six: server-timed review/confirmation changes impacts; the agent supports impact/owner and decision-lineage questions.
4. By hour eight: reviewed Actions survive restart; replay, stale/expired inputs, different-date input, and one concurrent-update check are verified.
5. By hour ten: README, measured checks, and working demo are ready; remaining time is fix/submission buffer.

No extra approval round is introduced. These changes address the identified contract blockers in the plans; actual code and tests must still demonstrate that they are implemented correctly.
