import { getApiBaseUrl } from './runtimeConfig';
export function withQuery(path: string, params: Record<string, string | number | null | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') {
      query.set(key, String(value));
    }
  });
  const qs = query.toString();
  return qs ? `${path}?${qs}` : path;
}

export function formatApiErrorDetail(detail: unknown): string | null {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (!item || typeof item !== 'object') return String(item);
      const row = item as Record<string, unknown>;
      const loc = Array.isArray(row.loc) ? row.loc.join('.') : '';
      const msg = typeof row.msg === 'string' ? row.msg : JSON.stringify(row);
      return loc ? `${loc}: ${msg}` : msg;
    });
    return parts.filter(Boolean).join('; ') || null;
  }
  if (detail && typeof detail === 'object') {
    // 机读 detail 的既有形状是 `{code, message}`。`message` 是给人看的那一半，
    // 直接 JSON.stringify 会把 `{"code":"place_provider_unavailable",…}` 原样
    // 显示到输入框下面。只带 code 的站点（如 report_out_of_date）另有专门的
    // 前端分支读 `body.detail.code`，走不到这里的展示位。
    const record = detail as Record<string, unknown>;
    if (typeof record.message === 'string' && record.message.trim()) return record.message;
    return JSON.stringify(detail);
  }
  return null;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: unknown
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export const DEFAULT_TIMEOUT_MS = 15_000;

export const SLOW_TIMEOUT_MS = 30_000;

export const LLM_TIMEOUT_MS = 60_000;

export const DOCUMENT_TIMEOUT_MS = 120_000;

export function requestSignal(init: RequestInit | undefined, timeoutMs: number): AbortSignal {
  return init?.signal ?? AbortSignal.timeout(timeoutMs);
}

export function readableTransportError(reason: unknown, timeoutMs: number): unknown {
  if ((reason as { name?: string } | null)?.name === 'TimeoutError') {
    return new Error(`请求超时（${Math.round(timeoutMs / 1000)} 秒未响应）`);
  }
  return reason;
}

export async function fetchJson<T>(
  path: string,
  init?: RequestInit,
  timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  let response: Response;
  try {
    response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...init,
      headers,
      signal: requestSignal(init, timeoutMs),
    });
  } catch (reason) {
    throw readableTransportError(reason, timeoutMs);
  }

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    let body: unknown = null;
    try {
      body = await response.json();
      const record = body && typeof body === 'object' ? body as Record<string, unknown> : null;
      message = formatApiErrorDetail(record?.detail)
        || (typeof record?.message === 'string' ? record.message : message);
    } catch {
      // keep HTTP status fallback
    }
    throw new ApiError(message, response.status, body);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function fetchBlob(path: string, init: RequestInit, timeoutMs: number = DEFAULT_TIMEOUT_MS): Promise<{
  blob: Blob;
  headers: Headers;
}> {
  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  let response: Response;
  try {
    response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...init,
      headers,
      signal: requestSignal(init, timeoutMs),
    });
  } catch (reason) {
    throw readableTransportError(reason, timeoutMs);
  }
  if (!response.ok) {
    let body: unknown = null;
    let message = `${response.status} ${response.statusText}`;
    try {
      body = await response.json();
      const record = body && typeof body === 'object' ? body as Record<string, unknown> : null;
      message = formatApiErrorDetail(record?.detail)
        || (typeof record?.message === 'string' ? record.message : message);
    } catch {
      // keep HTTP status fallback
    }
    throw new ApiError(message, response.status, body);
  }
  return {
    blob: await response.blob(),
    headers: response.headers,
  };
}
