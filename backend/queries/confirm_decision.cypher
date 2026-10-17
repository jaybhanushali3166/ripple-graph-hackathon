// Atomic forecast cutover. The GraphState match is the version gate: a stale
// dataset/revision matches no row, so every later clause creates or changes nothing.
// Parameters: see GraphWrites.confirm_decision.
MATCH (g:GraphState {id: 'workspace', dataset_id: $dataset, revision: $expected_revision})
MATCH (wi:WorkItem {id: $work_item_id})-[:HAS_FORECAST]->(old:Forecast {status: 'accepted'})
WHERE old.valid_to IS NULL
MATCH (old_dec:Decision)-[:ESTABLISHES]->(old)
SET old.valid_to = $effective_at
MERGE (s:Source {id: $source_id})
  ON CREATE SET s.type = $source_type, s.title = $source_title, s.body = $source_body,
                s.source_timestamp = $source_timestamp, s.content_hash = $content_hash
CREATE (fc:Forecast {id: $forecast_id, available_at: $available_at, valid_from: $effective_at,
                     status: 'accepted', recorded_at: $now, source_id: $source_id, quote: $quote})
CREATE (dec:Decision {id: $decision_id, summary: $summary, decided_at: $effective_at,
                      status: 'approved', source_id: $source_id, quote: $quote})
CREATE (wi)-[:HAS_FORECAST]->(fc)
CREATE (dec)-[:ESTABLISHES]->(fc)
CREATE (dec)-[:REVISES]->(wi)
CREATE (dec)-[:SUPERSEDES]->(old_dec)
CREATE (dec)-[:SUPPORTED_BY {source_id: $source_id, quote: $quote}]->(s)
CREATE (fc)-[:SUPPORTED_BY {source_id: $source_id, quote: $quote}]->(s)
SET g.revision = g.revision + 1
CREATE (:RequestRecord {id: $request_id, dataset_id: $dataset, operation: 'confirm_decision',
                        idempotency_key: $key, request_hash: $request_hash,
                        result_json: $result_json, committed_at: $now})
RETURN dec.id, g.revision
