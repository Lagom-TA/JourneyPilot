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
  return `<span data-bundle-map-marker="${escapeHtml(String(input.sequence))}" data-bundle-map-entity="${escapeHtml(input.entityId)}" data-bundle-map-kind="${escapeHtml(input.markerKind)}" data-transport-mode="${escapeHtml(input.mode)}" data-pin-color="${escapeHtml(color)}" style="width:${size}px;height:${size}px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:${escapeHtml(color)};color:#fff;font:700 12px/1 -apple-system,BlinkMacSystemFont,sans-serif;border:${endpoint ? 2 : 3}px solid #fff;box-shadow:${input.boxShadow};transform:${input.transform};transition:transform var(--dur-fast,120ms) var(--ease-standard,ease)">${escapeHtml(input.content)}</span>`;
}

export function buildGroupPinHtml(input: { groupId: string; color: string; count: number }): string {
  const { groupId, color, count } = input;
  return `<span data-bundle-map-group="${escapeHtml(groupId)}" style="width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:${escapeHtml(color)};color:#fff;font:700 13px/1 -apple-system,BlinkMacSystemFont,sans-serif;border:3px solid #fff;box-shadow:0 0 0 3px color-mix(in srgb, ${escapeHtml(color)} 18%, transparent),0 4px 12px rgba(0,0,0,.24)">${escapeHtml(String(count))}</span>`;
}
