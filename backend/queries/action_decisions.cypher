// Which of the given Decision ids exist. Parameters: $ids.
MATCH (d:Decision) WHERE d.id IN $ids RETURN d.id
