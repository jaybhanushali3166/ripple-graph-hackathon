import type { Forecast, HistoryResponse, Impact, ImpactResponse, Person, Source } from '../api/types';

export const canonicalNote = 'Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. Owner: Priya. This replaces decision DEC-12.';
export const endOfIstDay = (day: string) => Date.parse(`${day}T23:59:59.999+05:30`);
const baseline = Date.parse('2026-10-01T00:00:00+05:30');
export const people: Record<string, Person> = Object.fromEntries([
  ['priya', 'Priya'], ['lena', 'Lena'], ['omar', 'Omar'], ['eli', 'Eli'],
  ['maya', 'Maya'], ['nisha', 'Nisha'], ['leo', 'Leo'], ['noah', 'Noah'],
].map(([id, name]) => [`person_${id}`, { id: `person_${id}`, name }]));

export const workItems: Record<string, { name: string; date: string; owner: string; source: string; quote: string }> = {
  wi_sso: { name: 'Enterprise SSO', date: '2026-10-22', owner: 'person_lena', source: 'src_sso_plan', quote: 'Enterprise SSO requires identity migration. The recorded SSO forecast is October 22, 2026.' },
  wi_identity_migration: { name: 'Identity migration', date: '2026-10-21', owner: 'person_lena', source: 'src_identity_plan', quote: 'Identity migration depends on the permissions service. The recorded forecast is October 21, 2026.' },
  wi_permissions: { name: 'Permissions service', date: '2026-10-21', owner: 'person_priya', source: 'src_dec12', quote: 'Approved in DEC-12: permissions service delivery is October 21, 2026. Owner: Priya.' },
  wi_audit: { name: 'Audit logging', date: '2026-10-24', owner: 'person_omar', source: 'src_audit_plan', quote: 'Audit logging depends on the permissions service. The recorded audit forecast is October 24, 2026.' },
  wi_export: { name: 'Data export', date: '2026-10-22', owner: 'person_eli', source: 'src_export_plan', quote: 'Data export depends on the export worker. The recorded data export forecast is October 22, 2026.' },
  wi_export_worker: { name: 'Export worker', date: '2026-10-21', owner: 'person_eli', source: 'src_export_plan', quote: 'The export worker forecast is October 21, 2026. This work has no permissions dependency.' },
};
const customers = [
  { key: 'acme', id: 'com_acme_sso', name: 'Acme', due: '2026-10-23', root: 'wi_sso', path: ['wi_sso', 'wi_identity_migration', 'wi_permissions'], account: 'person_maya' },
  { key: 'birch', id: 'com_birch_audit', name: 'Birch', due: '2026-10-26', root: 'wi_audit', path: ['wi_audit', 'wi_permissions'], account: 'person_nisha' },
  { key: 'cedar', id: 'com_cedar_export', name: 'Cedar', due: '2026-10-23', root: 'wi_export', path: ['wi_export', 'wi_export_worker'], account: 'person_leo' },
  { key: 'delta', id: 'com_delta_sso', name: 'Delta', due: '2026-11-05', root: 'wi_sso', path: ['wi_sso', 'wi_identity_migration', 'wi_permissions'], account: 'person_noah' },
];
const makeSource = (id: string, title: string, body: string, type = 'document'): Source => ({ id, title, body, type, source_timestamp: baseline, content_hash: `development-fixture:${id}` });
export const sources: Record<string, Source> = {
  src_owners: makeSource('src_owners', 'Harbor · Ownership register', 'Priya owns permissions. Lena owns SSO and identity migration. Omar owns audit. Eli owns export and its worker. Maya owns the Acme account; Nisha owns Birch; Leo owns Cedar; Noah owns Delta.'),
  src_permissions_ticket: makeSource('src_permissions_ticket', 'PERM-42 · Permissions delivery', 'Priya is the accountable engineering owner. Accepted delivery assumptions are recorded through source-backed decisions.', 'ticket'),
  src_revised_permissions: makeSource('src_revised_permissions', 'Permissions · Approved delivery update', canonicalNote, 'engineering note'),
};
for (const [id, work] of Object.entries(workItems)) {
  const existing = sources[work.source];
  sources[work.source] = makeSource(work.source, `${work.name} · Delivery plan`, `${existing?.body ? existing.body + '\n\n' : ''}${work.quote}\n\nEngineering owner: ${people[work.owner].name}. The accepted baseline decision is ${id === 'wi_permissions' ? 'DEC-12' : `dec_baseline_${id}`}.`);
}
for (const customer of customers) {
  const id = `src_${customer.key}_handoff`;
  sources[id] = makeSource(id, `${customer.name} · Customer handoff`, `Customer: ${customer.name}\n\n${customer.name} is promised ${workItems[customer.root].name} by ${customer.due}. This commitment requires ${workItems[customer.root].name}.\n\nAccount owner: ${people[customer.account].name}.`, 'sales handoff');
}

export function impactFixture(changed: boolean, version: string, missingOwner = false): ImpactResponse {
  const impacts: Impact[] = customers.map(customer => {
    const root = workItems[customer.root];
    const conflict = changed && ['acme', 'birch'].includes(customer.key);
    const handoff = `src_${customer.key}_handoff`;
    const nodes = [
      { id: `cust_${customer.key}`, label: customer.name, kind: 'customer' as const },
      { id: customer.id, label: `${root.name} commitment`, kind: 'commitment' as const },
      ...customer.path.map((id, index) => ({ id, label: workItems[id].name, kind: index === 0 ? 'feature' as const : 'component' as const })),
    ];
    return {
      commitment_id: customer.id, customer: { id: `cust_${customer.key}`, name: customer.name }, title: root.name, due_at: endOfIstDay(customer.due),
      status: conflict ? 'date_conflict' : missingOwner && customer.key === 'acme' ? 'needs_verification' : 'no_detected_conflict',
      reasons: [...(conflict ? ['The permissions forecast falls after the customer promise. The recorded feature forecast needs replanning.'] : ['No date conflict detected on the recorded dependency path.']), ...(missingOwner && customer.key === 'acme' ? ['Engineering ownership is unresolved. Verify an accountable owner before saving.'] : [])],
      blockers: conflict ? [{ work_item_id: 'wi_permissions', name: 'Permissions service', forecast_id: 'forecast_permissions_revised', available_at: endOfIstDay('2026-10-28'), decision_id: 'dec_permissions_revised' }] : [],
      paths: [{ nodes, edges: nodes.slice(0, -1).map((node, index) => ({ from_id: node.id, to_id: nodes[index + 1].id, relation: index === 0 ? 'HAS_COMMITMENT' : index === 1 ? 'REQUIRES' : 'DEPENDS_ON', source_id: index < 2 ? handoff : workItems[node.id].source })) }],
      engineering_owner: missingOwner && customer.key === 'acme' ? null : people[conflict ? 'person_priya' : root.owner], account_owner: people[customer.account],
      citations: [{ source_id: handoff, quote: `${customer.name} is promised ${root.name} by ${customer.due}.` }, { source_id: conflict ? 'src_revised_permissions' : root.source, quote: conflict ? canonicalNote : root.quote }],
    };
  });
  return { evidence_version: version, as_of: Date.now(), impacts, completeness: { complete: !missingOwner, truncated: false, warnings: missingOwner ? ['Acme engineering ownership needs verification.'] : [] } };
}

export function historyFixture(id: string, changed: boolean, version: string, effectiveAt: number): HistoryResponse {
  const work = workItems[id];
  if (!work) throw new Error('Unknown fixture work item.');
  const initial: Forecast = { id: `forecast_baseline_${id}`, available_at: endOfIstDay(work.date), valid_from: baseline, valid_to: changed && id === 'wi_permissions' ? effectiveAt : null, decision_id: id === 'wi_permissions' ? 'DEC-12' : `dec_baseline_${id}`, citations: [{ source_id: work.source, quote: work.quote }] };
  return { evidence_version: version, forecasts: [initial, ...(changed && id === 'wi_permissions' ? [{ id: 'forecast_permissions_revised', available_at: endOfIstDay('2026-10-28'), valid_from: effectiveAt, valid_to: null, decision_id: 'dec_permissions_revised', citations: [{ source_id: 'src_revised_permissions', quote: canonicalNote }] }] : [])] };
}
