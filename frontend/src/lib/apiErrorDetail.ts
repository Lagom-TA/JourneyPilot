import { ApiError } from './http';

export interface ApiErrorDetail {
  code: string | null;
  message: string | null;
}

function detailRecord(error: unknown): Record<string, unknown> | null {
  if (!(error instanceof ApiError) || !error.body || typeof error.body !== 'object') return null;
  const detail = (error.body as Record<string, unknown>).detail;
  if (!detail || typeof detail !== 'object') return null;
  return detail as Record<string, unknown>;
}

export function apiErrorDetail(error: unknown): ApiErrorDetail {
  const record = detailRecord(error);
  if (!record) return { code: null, message: null };
  return {
    code: typeof record.code === 'string' ? record.code : null,
    message: typeof record.message === 'string' ? record.message : null,
  };
}

/* 空字符串按缺失处理，避免将空标识当作有效值。 */
export function apiErrorDetailString(error: unknown, key: string): string | null {
  const value = detailRecord(error)?.[key];
  return typeof value === 'string' && value ? value : null;
}
