
export const READOUT_PLACEHOLDER = '—';

/* 输入单位为毫秒，不能传入秒值。 */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return READOUT_PLACEHOLDER;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const minutes = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  // 舍入后的秒数可能到 60，需要向分钟进位。
  if (rem === 60) return `${minutes + 1}m00s`;
  return `${minutes}m${rem.toString().padStart(2, '0')}s`;
}

export function currencySymbol(currency: string | null | undefined): string {
  switch (currency) {
    case 'CNY':
    case 'RMB':
      return '¥';
    case 'EUR':
      return '€';
    default:
      return '$';
  }
}

export function formatCount(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return READOUT_PLACEHOLDER;
  return Math.round(value).toLocaleString('en-US');
}

export function formatTokens(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return READOUT_PLACEHOLDER;
  return Math.round(value).toLocaleString('en-US');
}

export function formatTokensCompact(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return READOUT_PLACEHOLDER;
  const n = Math.round(value);
  if (n < 1000) return n.toLocaleString('en-US');
  if (n < 1_000_000) {
    const k = n / 1000;
    return `${k >= 100 ? Math.round(k) : k.toFixed(1)}K`;
  }
  return `${(n / 1_000_000).toFixed(2)}M`;
}

/* 缺失金额不能显示为零，小于一分的非零金额也不能舍入成零。 */
export function formatCost(value: number | null | undefined, currency?: string | null): string {
  if (value == null || !Number.isFinite(value)) return READOUT_PLACEHOLDER;
  const symbol = currencySymbol(currency);
  if (value === 0) return `${symbol}0.00`;
  if (value > 0 && value < 0.01) return `<${symbol}0.01`;
  return `${symbol}${value.toFixed(2)}`;
}

/* 输入为已计算的比率，不是百分数或分子分母。 */
export function formatPercent(ratio: number | null | undefined, digits = 0): string {
  if (ratio == null || !Number.isFinite(ratio)) return READOUT_PLACEHOLDER;
  return `${(ratio * 100).toFixed(digits)}%`;
}
