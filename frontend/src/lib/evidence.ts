import type { Forecast, Impact } from '../api/types';
export function requiredRoots(impact: Impact): string[] {
  // R1's documented graph relation; validate exact spelling against kickoff JSON.
  return [...new Set(impact.paths.flatMap(path => path.edges.filter(edge => edge.from_id === impact.commitment_id && edge.relation === 'REQUIRES').map(edge => edge.to_id)))];
}
export function forecastAt(forecasts: Forecast[], asOf: number): Forecast | undefined {
  const matches = forecasts.filter(forecast => forecast.valid_from <= asOf && (forecast.valid_to === null || asOf < forecast.valid_to));
  return matches.length === 1 ? matches[0] : undefined;
}
