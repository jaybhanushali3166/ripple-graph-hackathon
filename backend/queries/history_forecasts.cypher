// Accepted forecasts of one work item with their establishing Decision and quotes.
// Parameters: $wid. The work item row is returned even when it has no accepted forecast
// (all other columns null), so an unknown work item is the only empty result.
// decision_id comes only from (Decision)-[:ESTABLISHES]->(Forecast), never from Decisions that
// merely REVISE the work item. supersedes_id and decision_summary are lineage additions.
MATCH (w:WorkItem {id: $wid})
OPTIONAL MATCH (w)-[:HAS_FORECAST]->(f:Forecast {status: 'accepted'})
OPTIONAL MATCH (d:Decision)-[:ESTABLISHES]->(f)
OPTIONAL MATCH (d)-[:SUPERSEDES]->(s:Decision)
RETURN DISTINCT w.id, f.id, f.available_at, f.valid_from, f.valid_to,
                d.id, s.id, d.summary
