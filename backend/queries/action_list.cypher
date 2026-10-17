// Saved Actions for one commitment, oldest first. Parameters: $id (commitment id).
MATCH (a:Action)-[:ADDRESSES]->(:Commitment {id: $id})
MATCH (a)-[:ASSIGNED_TO]->(p:Person)
OPTIONAL MATCH (a)-[:BASED_ON]->(d:Decision)
RETURN a.id, a.kind, p.id, a.body, a.citations_json, a.status, a.evidence_version, a.created_at, collect(d.id)
ORDER BY a.created_at, a.id
