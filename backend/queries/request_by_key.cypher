// Completed mutation recorded under a scoped idempotency key.
// Parameters: $id (hash of dataset, operation and key).
MATCH (r:RequestRecord {id: $id, dataset_id: $dataset, operation: $operation, idempotency_key: $key})
RETURN r.request_hash, r.result_json
