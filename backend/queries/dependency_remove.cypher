// Demo ablation: delete one DEPENDS_ON edge under the version gate and advance the revision.
// Parameters: $dataset, $expected_revision, $from_id, $to_id.
MATCH (g:GraphState {id: 'workspace', dataset_id: $dataset, revision: $expected_revision})
MATCH (:WorkItem {id: $from_id})-[e:DEPENDS_ON]->(:WorkItem {id: $to_id})
DELETE e
SET g.revision = g.revision + 1
RETURN g.revision
