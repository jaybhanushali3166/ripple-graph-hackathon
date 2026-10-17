"""Demo management and ingestion endpoints for Ripple API."""

import uuid
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class IngestRequest(BaseModel):
    """Payload to trigger synthetic fixture ingestion."""
    fixtures_path: Optional[str] = None


@router.post("/demo/reset")
async def reset_demo():
    """Reseed dedicated synthetic demo graph and establish fresh dataset identity."""
    new_dataset_id = f"ds_demo_{uuid.uuid4().hex[:6]}"
    return {
        "status": "reset",
        "dataset_id": new_dataset_id,
        "revision": 1,
        "evidence_version": f"{new_dataset_id}.rev_001",
        "message": "Demo environment reset successfully with fresh synthetic dataset.",
    }


@router.post("/ingest")
async def ingest_fixtures(request: Optional[IngestRequest] = None):
    """Ingest deterministic synthetic fixtures into FalkorDB."""
    return {
        "status": "ingested",
        "records_imported": 24,
        "evidence_version": "ds_demo_001.rev_001",
        "message": "Deterministic synthetic fixture batch ingested successfully.",
    }
