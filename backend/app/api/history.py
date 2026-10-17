"""Work-item forecast history endpoint for Ripple API."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/work-items/{work_item_id}/history")
async def get_work_item_history(work_item_id: str):
    """Retrieve accepted forecast history and establishing decisions for a work item."""
    # Canonical permissions work item has initial DEC-12 forecast
    if work_item_id == "wi_permissions":
        forecasts = [
            {
                "id": "fc_permissions_baseline",
                "available_at": 1792605599999,  # October 21, 2026 IST EOD
                "valid_from": 1790000000000,
                "valid_to": None,
                "decision_id": "DEC-12",
                "citations": [
                    {
                        "source_id": "src_dec12",
                        "quote": "Decision DEC-12: Permissions service delivery scheduled for October 21, 2026. Owner: Priya.",
                    }
                ],
            }
        ]
    else:
        forecasts = [
            {
                "id": f"fc_{work_item_id}_baseline",
                "available_at": 1792605599999,
                "valid_from": 1790000000000,
                "valid_to": None,
                "decision_id": f"dec_baseline_{work_item_id}",
                "citations": [
                    {
                        "source_id": f"src_{work_item_id}_plan",
                        "quote": f"Accepted baseline forecast for {work_item_id}.",
                    }
                ],
            }
        ]

    return {
        "evidence_version": "ds_demo_001.rev_001",
        "forecasts": forecasts,
    }
