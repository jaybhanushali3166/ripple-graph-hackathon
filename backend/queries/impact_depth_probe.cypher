// Commitments whose required root still has a fifth DEPENDS_ON hop beyond the bound.
// Parameters: $cid (nullable commitment filter).
MATCH (k:Commitment {status: 'open'})
WHERE $cid IS NULL OR k.id = $cid
MATCH (k)-[:REQUIRES]->(root:WorkItem)-[:DEPENDS_ON*5..5]->(deep:WorkItem)
RETURN DISTINCT k.id
