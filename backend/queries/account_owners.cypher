// Account owners (ACCOUNT_OWNER edges) with their provenance.
MATCH (p:Person)-[o:ACCOUNT_OWNER]->(c:Customer)
RETURN c.id, p.id, p.name, o.source_id, o.quote
