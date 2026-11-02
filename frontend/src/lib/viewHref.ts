/** 生成视图链接时保留部署 base（子路径部署由 VITE_BASE 控制）。 */
export function resolveViewHref(view: string, baseUrl: string | undefined): string {
  const base = baseUrl?.trim() || '/';
  const normalized = base.endsWith('/') ? base : `${base}/`;
  return `${normalized}?view=${encodeURIComponent(view)}`;
}

export function getViewHref(view: string): string {
  return resolveViewHref(view, import.meta.env.BASE_URL);
}
