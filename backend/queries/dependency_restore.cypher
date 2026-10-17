// Demo ablation: recreate a removed DEPENDS_ON edge with its original provenance.
// Parameters: $dataset, $expected_revision, $from_id, $to_id, $source_id, $quote.
MATCH (g:GraphState {id: 'workspace', dataset_id: $dataset, revision: $expected_revision})
MATCH (a:WorkItem {id: $from_id}), (b:WorkItem {id: $to_id})
WHERE NOT (a)-[:DEPENDS_ON]->(b)
CREATE (a)-[:DEPENDS_ON {source_id: $source_id, quote: $quote}]->(b)
SET g.revision = g.revision + 1
RETURN g.revision
