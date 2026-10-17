// Work items on the bounded path whose active accepted forecast is later than the due date
// (strict >), with the forecast's establishing Decision.
// Parameters: $as_of (epoch ms), $cid (nullable commitment filter).
MATCH (k:Commitment {status: 'open'})
WHERE $cid IS NULL OR k.id = $cid
MATCH (k)-[:REQUIRES]->(root:WorkItem)
MATCH (root)-[:DEPENDS_ON*0..4]->(w:WorkItem)-[:HAS_FORECAST]->(f:Forecast)
WHERE f.status = 'accepted'
  AND f.valid_from <= $as_of
  AND (f.valid_to IS NULL OR $as_of < f.valid_to)
  AND f.available_at > k.due_at
OPTIONAL MATCH (d:Decision)-[:ESTABLISHES]->(f)
RETURN DISTINCT k.id, w.id, w.name, f.id, f.available_at, f.source_id, f.quote,
                d.id, d.source_id, d.quote
