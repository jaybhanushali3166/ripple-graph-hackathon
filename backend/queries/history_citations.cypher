// Provenance quotes for a work item's accepted forecasts: the forecast's own SUPPORTED_BY
// edge (kind 'forecast') and its establishing Decision's SUPPORTED_BY edge (kind 'decision').
// Parameters: $wid.
MATCH (:WorkItem {id: $wid})-[:HAS_FORECAST]->(f:Forecast {status: 'accepted'})
OPTIONAL MATCH (f)-[fs:SUPPORTED_BY]->(:Source)
WITH f, collect(DISTINCT [fs.source_id, fs.quote]) AS forecast_quotes
OPTIONAL MATCH (d:Decision)-[:ESTABLISHES]->(f)
OPTIONAL MATCH (d)-[ds:SUPPORTED_BY]->(:Source)
RETURN f.id, forecast_quotes, collect(DISTINCT [ds.source_id, ds.quote])
