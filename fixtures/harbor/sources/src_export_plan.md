PROJECT PLAN - Data Export
Owner: Eli   Last updated: 2026-09-29

Scope: scheduled CSV export of tenant data.

Customer commitments:
- Cedar's data export commitment requires the data export feature.

Dependencies:
- The data export feature depends on the export worker component.
  The worker runs the nightly jobs and has no link to the permissions service.

Schedule:
- Export worker: forecast available October 19, 2026.
- Data export feature: forecast available October 21, 2026.
