import { describe, expect, it } from 'vitest';
import { forecastAt, requiredRoots } from '../lib/evidence';
import { historyFixture, impactFixture } from '../mocks/fixtures';

describe('forecast display semantics', () => {
  it('keeps a recorded feature forecast separate from a late dependency', () => {
    const asOf = Date.now(), impact = impactFixture(true, 'one').impacts[0];
    const feature = historyFixture('wi_sso', true, 'one', asOf - 10);
    const dependency = historyFixture('wi_permissions', true, 'one', asOf - 10);
    expect(requiredRoots(impact)).toEqual(['wi_sso']);
    expect(forecastAt(feature.forecasts, asOf)?.available_at).not.toBe(forecastAt(dependency.forecasts, asOf)?.available_at);
    expect(forecastAt(dependency.forecasts, asOf)?.decision_id).toBe('dec_permissions_revised');
    expect(forecastAt(dependency.forecasts, asOf - 20)?.decision_id).toBe('DEC-12');
  });
  it('does not pick an arbitrary forecast when accepted intervals overlap', () => {
    const history = historyFixture('wi_sso', false, 'one', Date.now());
    expect(forecastAt([...history.forecasts, { ...history.forecasts[0], id: 'conflicting' }], Date.now())).toBeUndefined();
  });
  it('preserves R1 owners for affected and unaffected controls in explicit fixtures', () => {
    expect(impactFixture(false, 'before').impacts.map(item => item.engineering_owner?.name)).toEqual(['Lena', 'Omar', 'Eli', 'Lena']);
    expect(impactFixture(true, 'after').impacts.map(item => item.engineering_owner?.name)).toEqual(['Priya', 'Priya', 'Eli', 'Lena']);
  });
});
