// Every open commitment, even one with no customer or requirement link.
// Parameters: $cid (nullable commitment filter).
MATCH (k:Commitment {status: 'open'})
WHERE $cid IS NULL OR k.id = $cid
OPTIONAL MATCH (c:Customer)-[hc:HAS_COMMITMENT]->(k)
RETURN k.id, k.title, k.due_at, c.id, c.name, hc.source_id, hc.quote
