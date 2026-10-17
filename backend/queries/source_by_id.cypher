MATCH (s:Source {id: $id})
RETURN s.id, s.type, s.title, s.body, s.source_timestamp, s.content_hash
