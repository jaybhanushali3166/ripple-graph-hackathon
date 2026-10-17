// Alias nodes point at every candidate entity.
MATCH (a:Alias {text_lower: $q})-[:REFERS_TO]->(e)
RETURN e.id, labels(e)[0], coalesce(e.name, e.title, e.summary)
