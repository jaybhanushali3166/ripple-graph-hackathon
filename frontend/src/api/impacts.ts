import { request } from './client';
import type { HistoryResponse, ImpactResponse, Source } from './types';
export const getImpacts = (signal?: AbortSignal) => request<ImpactResponse>('/impacts', { signal });
export const getSource = (id: string, signal?: AbortSignal) => request<Source>(`/sources/${encodeURIComponent(id)}`, { signal });
export const getHistory = (id: string, signal?: AbortSignal) => request<HistoryResponse>(`/work-items/${encodeURIComponent(id)}/history`, { signal });
