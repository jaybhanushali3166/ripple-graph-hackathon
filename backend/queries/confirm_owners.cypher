// Engineering owners (OWNS) of one work item. Parameters: $id.
MATCH (p:Person)-[:OWNS]->(:WorkItem {id: $id})
RETURN p.id
