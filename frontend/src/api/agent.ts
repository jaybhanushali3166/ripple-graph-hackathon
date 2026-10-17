import { post } from './client';
import type { AgentRequest, AgentResponse } from './types';
export const runAgent = (payload: AgentRequest, signal?: AbortSignal) => post<AgentResponse>('/agent/run', payload, signal);
