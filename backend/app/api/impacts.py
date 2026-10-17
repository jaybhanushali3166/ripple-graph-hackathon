"""Impact query endpoint for Ripple API."""

import os
import time
from typing import Optional

from fastapi import APIRouter, Response

router = APIRouter()

DEV_MOCKS = os.getenv("DEV_MOCKS", "true").lower() in ("true", "1", "yes")

# Canonical baseline timestamps (IST end-of-day in UTC epoch ms)
# 2026-10-23 23:59:59.999 IST = 1792778399999 ms
# 2026-10-26 23:59:59.999 IST = 1793037599999 ms
# 2026-11-05 23:59:59.999 IST = 1793901599999 ms
CANONICAL_MOCK_IMPACTS = [
    {
        "commitment_id": "com_acme_sso",
        "customer": {"id": "cust_acme", "name": "Acme Corp"},
        "title": "Single Sign-On Integration",
        "due_at": 1792778399999,
        "status": "no_detected_conflict",
        "reasons": ["Baseline accepted forecast precedes commitment deadline"],
        "blockers": [],
        "paths": [
            {
                "nodes": [
                    {"id": "cust_acme", "label": "Acme Corp", "kind": "customer"},
                    {"id": "com_acme_sso", "label": "Single Sign-On Integration", "kind": "commitment"},
                    {"id": "wi_sso", "label": "SSO Feature", "kind": "feature"},
                    {"id": "wi_identity_migration", "label": "Identity Migration", "kind": "component"},
                    {"id": "wi_permissions", "label": "Permissions Service", "kind": "component"},
                ],
                "edges": [
                    {"from_id": "cust_acme", "to_id": "com_acme_sso", "relation": "HAS_COMMITMENT", "source_id": "src_acme_handoff"},
                    {"from_id": "com_acme_sso", "to_id": "wi_sso", "relation": "REQUIRES", "source_id": "src_acme_handoff"},
                    {"from_id": "wi_sso", "to_id": "wi_identity_migration", "relation": "DEPENDS_ON", "source_id": "src_sso_plan"},
                    {"from_id": "wi_identity_migration", "to_id": "wi_permissions", "relation": "DEPENDS_ON", "source_id": "src_identity_plan"},
                ],
            }
        ],
        "engineering_owner": {"id": "person_lena", "name": "Lena Chen"},
        "account_owner": {"id": "person_maya", "name": "Maya Lin"},
        "citations": [
            {
                "source_id": "src_acme_handoff",
                "quote": "Acme SSO integration deadline agreed for October 23, 2026.",
            }
        ],
    },
    {
        "commitment_id": "com_birch_audit",
        "customer": {"id": "cust_birch", "name": "Birch Technologies"},
        "title": "Audit Log Export Service",
        "due_at": 1793037599999,
        "status": "no_detected_conflict",
        "reasons": ["Baseline accepted forecast precedes commitment deadline"],
        "blockers": [],
        "paths": [
            {
                "nodes": [
                    {"id": "cust_birch", "label": "Birch Technologies", "kind": "customer"},
                    {"id": "com_birch_audit", "label": "Audit Log Export Service", "kind": "commitment"},
                    {"id": "wi_audit", "label": "Audit Logging", "kind": "feature"},
                    {"id": "wi_permissions", "label": "Permissions Service", "kind": "component"},
                ],
                "edges": [
                    {"from_id": "cust_birch", "to_id": "com_birch_audit", "relation": "HAS_COMMITMENT", "source_id": "src_birch_handoff"},
                    {"from_id": "com_birch_audit", "to_id": "wi_audit", "relation": "REQUIRES", "source_id": "src_birch_handoff"},
                    {"from_id": "wi_audit", "to_id": "wi_permissions", "relation": "DEPENDS_ON", "source_id": "src_audit_plan"},
                ],
            }
        ],
        "engineering_owner": {"id": "person_omar", "name": "Omar Patel"},
        "account_owner": {"id": "person_nisha", "name": "Nisha Gupta"},
        "citations": [
            {
                "source_id": "src_birch_handoff",
                "quote": "Birch audit log export capability required by October 26, 2026.",
            }
        ],
    },
    {
        "commitment_id": "com_cedar_export",
        "customer": {"id": "cust_cedar", "name": "Cedar Enterprises"},
        "title": "Custom Data Export Pipeline",
        "due_at": 1792778399999,
        "status": "no_detected_conflict",
        "reasons": ["Baseline accepted forecast precedes commitment deadline"],
        "blockers": [],
        "paths": [
            {
                "nodes": [
                    {"id": "cust_cedar", "label": "Cedar Enterprises", "kind": "customer"},
                    {"id": "com_cedar_export", "label": "Custom Data Export Pipeline", "kind": "commitment"},
                    {"id": "wi_export", "label": "Data Export", "kind": "feature"},
                    {"id": "wi_export_worker", "label": "Export Worker", "kind": "component"},
                ],
                "edges": [
                    {"from_id": "cust_cedar", "to_id": "com_cedar_export", "relation": "HAS_COMMITMENT", "source_id": "src_cedar_handoff"},
                    {"from_id": "com_cedar_export", "to_id": "wi_export", "relation": "REQUIRES", "source_id": "src_cedar_handoff"},
                    {"from_id": "wi_export", "to_id": "wi_export_worker", "relation": "DEPENDS_ON", "source_id": "src_export_plan"},
                ],
            }
        ],
        "engineering_owner": {"id": "person_eli", "name": "Eli Vance"},
        "account_owner": {"id": "person_leo", "name": "Leo Rossi"},
        "citations": [
            {
                "source_id": "src_cedar_handoff",
                "quote": "Cedar data export pipeline promised for delivery by October 23, 2026.",
            }
        ],
    },
    {
        "commitment_id": "com_delta_sso",
        "customer": {"id": "cust_delta", "name": "Delta Logistics"},
        "title": "Enterprise SSO Deployment",
        "due_at": 1793901599999,
        "status": "no_detected_conflict",
        "reasons": ["Baseline accepted forecast precedes commitment deadline"],
        "blockers": [],
        "paths": [
            {
                "nodes": [
                    {"id": "cust_delta", "label": "Delta Logistics", "kind": "customer"},
                    {"id": "com_delta_sso", "label": "Enterprise SSO Deployment", "kind": "commitment"},
                    {"id": "wi_sso", "label": "SSO Feature", "kind": "feature"},
                    {"id": "wi_identity_migration", "label": "Identity Migration", "kind": "component"},
                    {"id": "wi_permissions", "label": "Permissions Service", "kind": "component"},
                ],
                "edges": [
                    {"from_id": "cust_delta", "to_id": "com_delta_sso", "relation": "HAS_COMMITMENT", "source_id": "src_delta_handoff"},
                    {"from_id": "com_delta_sso", "to_id": "wi_sso", "relation": "REQUIRES", "source_id": "src_delta_handoff"},
                    {"from_id": "wi_sso", "to_id": "wi_identity_migration", "relation": "DEPENDS_ON", "source_id": "src_sso_plan"},
                    {"from_id": "wi_identity_migration", "to_id": "wi_permissions", "relation": "DEPENDS_ON", "source_id": "src_identity_plan"},
                ],
            }
        ],
        "engineering_owner": {"id": "person_lena", "name": "Lena Chen"},
        "account_owner": {"id": "person_noah", "name": "Noah Kim"},
        "citations": [
            {
                "source_id": "src_delta_handoff",
                "quote": "Delta Logistics SSO deployment scheduled by November 5, 2026.",
            }
        ],
    },
]


@router.get("/impacts")
async def get_impacts(as_of: Optional[int] = None, response: Response = None):
    """Retrieve commitment impact summaries and evidence paths.

    When DEV_MOCKS=True, returns the canonical 4-customer scenario payload.
    """
    server_now = as_of if as_of is not None else int(time.time() * 1000)

    if DEV_MOCKS:
        if response is not None:
            response.headers["X-Mock-Mode"] = "true"
        return {
            "evidence_version": "ds_demo_001.rev_001",
            "as_of": server_now,
            "impacts": CANONICAL_MOCK_IMPACTS,
            "completeness": {
                "complete": True,
                "truncated": False,
                "warnings": [],
            },
        }

    # Production path will delegate to GraphRepository
    return {
        "evidence_version": "ds_demo_001.rev_001",
        "as_of": server_now,
        "impacts": [],
        "completeness": {
            "complete": True,
            "truncated": False,
            "warnings": [],
        },
    }
