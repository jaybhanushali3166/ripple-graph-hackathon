// Who knows a work item: its owner, people who discussed it in chats, tickets and meetings,
// and members of the team responsible for it. Every row carries its provenance.
// Parameters: $wid.
MATCH (w:WorkItem {id: $wid})
OPTIONAL MATCH (p:Person)-[r:OWNS|DISCUSSED]->(w)
WITH w, collect([p.id, p.name, type(r), r.source_id, r.quote]) AS direct
OPTIONAL MATCH (m:Person)-[mo:MEMBER_OF]->(t:Team)-[rf:RESPONSIBLE_FOR]->(w)
WITH direct, collect([m.id, m.name, 'MEMBER_OF:' + t.name, mo.source_id, mo.quote]) AS team
UNWIND direct + team AS row
WITH row WHERE row[0] IS NOT NULL
RETURN row[0], row[1], row[2], row[3], row[4]
