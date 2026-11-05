export function escapeHtml(value: string): string {
  const replacements: Record<string, string> = {
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;',
  };
  return value.replace(/[&<>"']/g, (character) => replacements[character]);
}

export interface PlacePinHtmlInput {
  sequence: number;
  entityId: string;
  markerKind: string;
  mode: string;
  color: string;
  endpoint: boolean;
  size: number;
  content: string;
  boxShadow: string;
  transform: string;
}

/** Leaflet DivIcon 只接受 HTML 字符串；所有属性/文本插值都必须先转义。 */
export function buildPlacePinHtml(input: PlacePinHtmlInput): string {
  const { size, endpoint, color } = input;
  const content = endpoint ? '<span class="journey-endpoint-dot" aria-hidden="true"></span>' : escapeHtml(input.content);
  return `<span data-bundle-map-marker="${escapeHtml(String(input.sequence))}" data-bundle-map-entity="${escapeHtml(input.entityId)}" data-bundle-map-kind="${escapeHtml(input.markerKind)}" data-transport-mode="${escapeHtml(input.mode)}" data-pin-color="${escapeHtml(color)}" style="--map-pin-color:${escapeHtml(color)};width:${size}px;height:${size}px;border-radius:var(--radius-circle);display:flex;align-items:center;justify-content:center;background:${escapeHtml(color)};color:rgb(var(--color-white-rgb));font:700 12px/1 -apple-system,BlinkMacSystemFont,sans-serif;border:${endpoint ? 2 : 3}px solid rgb(var(--color-white-rgb));box-shadow:${input.boxShadow};transform:${input.transform};transition:transform var(--dur-fast) var(--ease-standard)">${content}</span>`;
}

export function buildGroupPinHtml(input: { groupId: string; color: string; count: number }): string {
  const { groupId, color, count } = input;
  return `<span data-bundle-map-group="${escapeHtml(groupId)}" style="--map-pin-color:${escapeHtml(color)};width:34px;height:34px;border-radius:var(--radius-circle);display:flex;align-items:center;justify-content:center;background:${escapeHtml(color)};color:rgb(var(--color-white-rgb));font:700 13px/1 -apple-system,BlinkMacSystemFont,sans-serif;border:3px solid rgb(var(--color-white-rgb));box-shadow:var(--shadow-map-pin-group)">${escapeHtml(String(count))}</span>`;
}
