// Which of the given ids already belong to a Decision or Forecast. Parameters: $ids.
MATCH (n) WHERE n.id IN $ids AND (n:Decision OR n:Forecast) RETURN n.id
