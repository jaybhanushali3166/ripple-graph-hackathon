/** Human label for a decision ID: DEC codes as-is, seeded baselines as "Baseline plan". */
export function decisionLabel(id: string): string {
  if (/^DEC-\d+$/i.test(id)) return id.toUpperCase();
  if (id.startsWith('dec_baseline_')) return 'Baseline plan';
  return 'Recorded decision';
}
