type ClassValue = string | number | false | null | undefined | Record<string, boolean>;

export function cn(...classes: ClassValue[]): string {
  const out: string[] = [];
  for (const c of classes) {
    if (!c) continue;
    if (typeof c === 'string' || typeof c === 'number') {
      out.push(String(c));
    } else {
      for (const [key, val] of Object.entries(c)) {
        if (val) out.push(key);
      }
    }
  }
  return out.join(' ');
}

let idCounter = 0;

export function generateId(): string {
  idCounter += 1;
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}${idCounter.toString(36)}`;
}

export function truncate(str: string, maxLength: number): string {
  if (!str) return '';
  return str.length > maxLength ? `${str.slice(0, maxLength)}…` : str;
}
