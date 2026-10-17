// Persist a reviewed Action behind the version gate. The revision is NOT incremented.
MATCH (g:GraphState {id: 'workspace', dataset_id: $dataset, revision: $expected_revision})
MATCH (c:Commitment {id: $commitment_id})
MATCH (p:Person {id: $assignee_id})
MATCH (d:Decision) WHERE d.id IN $decision_ids
WITH g, c, p, collect(d) AS decisions
WHERE size(decisions) = $decision_count
CREATE (a:Action {id: $action_id, kind: $kind, body: $body, status: 'reviewed',
                  created_at: $now, evidence_version: $evidence_version, citations_json: $citations_json})
CREATE (a)-[:ADDRESSES]->(c)
CREATE (a)-[:ASSIGNED_TO]->(p)
CREATE (:RequestRecord {id: $request_id, dataset_id: $dataset, operation: 'save_action',
                        idempotency_key: $key, request_hash: $request_hash,
                        result_json: $result_json, committed_at: $now})
WITH a, decisions
UNWIND decisions AS d
CREATE (a)-[:BASED_ON]->(d)
RETURN count(*)
