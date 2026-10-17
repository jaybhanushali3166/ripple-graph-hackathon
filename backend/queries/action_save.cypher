// Persist a reviewed Action behind the version gate. The revision is NOT incremented.
MATCH (g:GraphState {id: 'workspace', dataset_id: $dataset, revision: $expected_revision})
MATCH (c:Commitment {id: $commitment_id})
MATCH (p:Person {id: $assignee_id})
// The revision does not change here, so the gate alone cannot stop two identical concurrent
// saves. Refuse to write when this request's record or Action already exists; the caller then
// re-checks the replay and returns the stored result.
OPTIONAL MATCH (existing_request:RequestRecord {id: $request_id})
OPTIONAL MATCH (existing_action:Action {id: $action_id})
WITH g, c, p, existing_request, existing_action
WHERE existing_request IS NULL AND existing_action IS NULL
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
