import { useCallback, useState } from 'react';
import { getImpacts } from '../api/impacts';
import { useResource } from './useResource';

export function useWorkspace() {
  const [revision, setRevision] = useState(0);
  const [selectedId, select] = useState<string | null>(null);
  const resource = useResource(`impacts:${revision}`, getImpacts);
  const selected = resource.data?.impacts.find(impact => impact.commitment_id === selectedId) ?? resource.data?.impacts[0] ?? null;
  const refresh = useCallback(() => setRevision(value => value + 1), []);
  return { ...resource, selected, select, refresh };
}
