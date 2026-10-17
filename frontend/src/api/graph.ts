import { post, request } from './client';
import type { DemoResetResponse, DependencyToggle, DependencyToggleResponse, ExpertsResponse, GraphView, SourceList } from './types';
export const getGraph = (signal?: AbortSignal) => request<GraphView>('/graph', { signal });
export const getSources = (signal?: AbortSignal) => request<SourceList>('/sources', { signal });
export const getExperts = (id: string, signal?: AbortSignal) => request<ExpertsResponse>(`/work-items/${encodeURIComponent(id)}/experts`, { signal });
export const setDependency = (payload: DependencyToggle) => post<DependencyToggleResponse>('/demo/dependency', payload);
export const resetDemo = () => post<DemoResetResponse>('/demo/reset', {});
