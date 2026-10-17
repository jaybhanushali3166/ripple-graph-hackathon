// Every bounded path (0..4 DEPENDS_ON hops) from each open commitment's required root.
// Parameters: $cid (nullable commitment filter). Edge lists are in graph direction.
MATCH (k:Commitment {status: 'open'})
WHERE $cid IS NULL OR k.id = $cid
MATCH (k)-[rq:REQUIRES]->(root:WorkItem)
MATCH p = (root)-[:DEPENDS_ON*0..4]->(w:WorkItem)
RETURN k.id, rq.source_id, rq.quote, root.id,
       [n IN nodes(p) | n.id],
       [r IN relationships(p) | r.source_id],
       [r IN relationships(p) | r.quote]
