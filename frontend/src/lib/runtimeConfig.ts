type ImportMetaWithEnv = ImportMeta & {
  env?: {
    VITE_API_BASE?: string;
  };
};

function readEnv(name: 'VITE_API_BASE'): string | undefined {
  return (import.meta as ImportMetaWithEnv).env?.[name];
}

/* Vite 在转换时固定 import.meta.env，因此解析逻辑不直接读取环境。 */
export function resolveApiBaseUrl(configured: string | undefined): string {
  const raw = configured?.trim();
  if (!raw) return '/api';
  return raw.replace(/\/+$/, '');
}

export function getApiBaseUrl(): string {
  return resolveApiBaseUrl(readEnv('VITE_API_BASE'));
}
