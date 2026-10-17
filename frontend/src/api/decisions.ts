import { post } from './client';
import type { ConfirmRequest, ConfirmResponse, DecisionPreview, PreviewRequest } from './types';
export const previewDecision = (payload: PreviewRequest) => post<DecisionPreview>('/decisions/preview', payload);
export const confirmDecision = (payload: ConfirmRequest) => post<ConfirmResponse>('/decisions/confirm', payload);
