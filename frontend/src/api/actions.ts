import { post, request } from './client';
import type { ActionRequest, ActionResponse, ActionsResponse } from './types';
export const saveAction = (payload: ActionRequest) => post<ActionResponse>('/actions', payload);
export const getActions = (id: string, signal?: AbortSignal) => request<ActionsResponse>(`/actions?commitment_id=${encodeURIComponent(id)}`, { signal });
