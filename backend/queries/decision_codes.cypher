// Human-readable decision codes already in use ("DEC-<n>"), for numbering the next one.
MATCH (d:Decision) WHERE d.id STARTS WITH 'DEC-' RETURN d.id
