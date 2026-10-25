
const ALLOWED_SCHEMES = new Set(['http:', 'https:', 'mailto:']);

export function isSafeHref(href: string | null | undefined): boolean {
  if (href == null) return false;
  const trimmed = href.trim();
  if (!trimmed) return false;

  if (trimmed.startsWith('#')) return true;

  // 协议相对 URL 指向外部主机，不能按站内相对路径放行。
  if (trimmed.startsWith('//')) return false;

  const schemeMatch = /^([a-zA-Z][a-zA-Z0-9+.-]*):/.exec(trimmed);
  if (schemeMatch) {
    return ALLOWED_SCHEMES.has(`${schemeMatch[1].toLowerCase()}:`);
  }

  return true;
}

export function safeHref(href: string | null | undefined): string | undefined {
  if (!isSafeHref(href)) return undefined;
  return href!.trim();
}
