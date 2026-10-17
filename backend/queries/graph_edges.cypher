// Display edges for the dependency graph view: the same relationships impact detection walks.
MATCH (a)-[r:HAS_COMMITMENT|REQUIRES|DEPENDS_ON]->(b)
RETURN a.id, b.id, type(r), r.source_id
