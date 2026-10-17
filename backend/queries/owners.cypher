// Engineering owners (OWNS edges) with their provenance.
MATCH (p:Person)-[o:OWNS]->(w:WorkItem)
RETURN w.id, p.id, p.name, o.source_id, o.quote
