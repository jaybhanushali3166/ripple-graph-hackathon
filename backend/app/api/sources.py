"""Source inspection endpoint for Ripple API."""

import hashlib
from typing import Dict
from fastapi import APIRouter

router = APIRouter()

KNOWN_SOURCES: Dict[str, Dict[str, str]] = {
    "src_acme_handoff": {
        "title": "Acme Handoff Specification",
        "type": "handoff_spec",
        "body": "Acme SSO integration deadline agreed for October 23, 2026. Account owner: Maya Lin.",
    },
    "src_birch_handoff": {
        "title": "Birch Audit Logging Handoff",
        "type": "handoff_spec",
        "body": "Birch audit log export capability required by October 26, 2026. Account owner: Nisha Gupta.",
    },
    "src_cedar_handoff": {
        "title": "Cedar Data Export Handoff",
        "type": "handoff_spec",
        "body": "Cedar data export pipeline promised for delivery by October 23, 2026. Account owner: Leo Rossi.",
    },
    "src_delta_handoff": {
        "title": "Delta Logistics SSO Handoff",
        "type": "handoff_spec",
        "body": "Delta Logistics SSO deployment scheduled by November 5, 2026. Account owner: Noah Kim.",
    },
    "src_permissions_ticket": {
        "title": "Permissions Service Delivery Update",
        "type": "ticket",
        "body": "Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. Owner: Priya. This replaces decision DEC-12.",
    },
    "src_dec12": {
        "title": "Decision DEC-12: Permissions Service Delivery",
        "type": "decision_record",
        "body": "Decision DEC-12: Permissions service delivery scheduled for October 21, 2026. Owner: Priya.",
    },
    "src_sso_plan": {
        "title": "SSO Architecture Plan",
        "type": "architecture_doc",
        "body": "Single Sign-On implementation plan and dependency specification.",
    },
    "src_identity_plan": {
        "title": "Identity Migration Plan",
        "type": "architecture_doc",
        "body": "Identity migration component architecture and permissions dependency.",
    },
    "src_audit_plan": {
        "title": "Audit Service Plan",
        "type": "architecture_doc",
        "body": "Audit log export service architecture and dependency mapping.",
    },
    "src_export_plan": {
        "title": "Export Service Plan",
        "type": "architecture_doc",
        "body": "Data export worker service architecture and queue mapping.",
    },
    "src_owners": {
        "title": "Engineering and Account Ownership Roster",
        "type": "roster",
        "body": "Ownership assignments: Priya (permissions), Lena (sso, identity migration), Omar (audit), Eli (export), Maya (Acme), Nisha (Birch), Leo (Cedar), Noah (Delta).",
    },
}


@router.get("/sources/{source_id}")
async def get_source(source_id: str):
    """Retrieve source document content, metadata, and deterministic content hash."""
    known = KNOWN_SOURCES.get(source_id)
    if known:
        body = known["body"]
        title = known["title"]
        source_type = known["type"]
    else:
        title = f"Source {source_id}"
        source_type = "document"
        body = f"Source body for {source_id} establishing provenance and supporting evidence."

    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

    return {
        "id": source_id,
        "type": source_type,
        "title": title,
        "body": body,
        "source_timestamp": 1792195200000,
        "content_hash": content_hash,
    }
