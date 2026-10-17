// Case-insensitive exact match on id, name, title or summary. __LABEL__ is replaced by the
// repository from a fixed label table (never from user input); $q is already lower-cased.
MATCH (e:__LABEL__)
WHERE toLower(e.id) = $q
   OR toLower(coalesce(e.name, '')) = $q
   OR toLower(coalesce(e.title, '')) = $q
   OR toLower(coalesce(e.summary, '')) = $q
RETURN e.id, coalesce(e.name, e.title, e.summary)
