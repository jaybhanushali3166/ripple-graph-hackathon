// Number of active accepted forecasts for every work item on a bounded path
// (0 = missing evidence, more than 1 = conflicting evidence).
// Parameters: $as_of (epoch ms), $cid (nullable commitment filter).
MATCH (k:Commitment {status: 'open'})
WHERE $cid IS NULL OR k.id = $cid
MATCH (k)-[:REQUIRES]->(root:WorkItem)
MATCH (root)-[:DEPENDS_ON*0..4]->(w:WorkItem)
OPTIONAL MATCH (w)-[:HAS_FORECAST]->(f:Forecast)
WHERE f.status = 'accepted'
  AND f.valid_from <= $as_of
  AND (f.valid_to IS NULL OR $as_of < f.valid_to)
RETURN k.id, w.id, count(DISTINCT f)
