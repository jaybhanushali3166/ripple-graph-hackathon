// Display nodes for the dependency graph view. The kind of a work item is its stored kind.
MATCH (c:Customer) RETURN c.id AS id, c.name AS label, 'customer' AS kind
UNION ALL
MATCH (k:Commitment {status: 'open'}) RETURN k.id AS id, k.title AS label, 'commitment' AS kind
UNION ALL
MATCH (w:WorkItem) RETURN w.id AS id, w.name AS label, w.kind AS kind
