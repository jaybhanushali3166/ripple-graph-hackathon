// Every Decision with the work item it revises, so notes can name codes created at runtime.
MATCH (d:Decision)-[:REVISES]->(w:WorkItem) RETURN d.id, w.id
