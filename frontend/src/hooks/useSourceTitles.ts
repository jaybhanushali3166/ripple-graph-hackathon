import { createContext, useContext } from 'react';
import { getSources } from '../api/graph';
import { useResource } from './useResource';

export const SourceTitles = createContext<Record<string, string>>({});
export const useSourceTitle = (id: string) => useContext(SourceTitles)[id];

/** Source ID -> title, loaded once per evidence version. Failure only loses the nicer labels. */
export function useSourceTitleMap(version: string | null): Record<string, string> {
  const result = useResource(version ? `sources:${version}` : null, async signal => {
    const list = await getSources(signal);
    return Object.fromEntries(list.sources.map(source => [source.id, source.title]));
  });
  return result.data ?? {};
}
