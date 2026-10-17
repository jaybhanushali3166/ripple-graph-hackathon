// Active accepted forecasts of a work item with their establishing Decisions.
// One row per (forecast, decision); a missing work item returns no rows.
// Parameters: $id (work item id).
MATCH (wi:WorkItem {id: $id})
OPTIONAL MATCH (wi)-[:HAS_FORECAST]->(f:Forecast {status: 'accepted'})
WHERE f.valid_to IS NULL
OPTIONAL MATCH (d:Decision)-[:ESTABLISHES]->(f)
RETURN wi.id, f.id, f.valid_from, d.id, f.available_at, wi.name
