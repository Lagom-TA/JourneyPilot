import type { ControlledTripIdentity, PlaceIdentity } from "../types/planner";

export function tripIdentityError(input: {
  origin: PlaceIdentity | null;
  destinations: Array<PlaceIdentity | null>;
  start_date: string;
  end_date: string;
  party: ControlledTripIdentity["party"] | null;
  style: ControlledTripIdentity["style"] | null;
}): string | null {
  if (
    !input.origin ||
    !input.destinations.length ||
    input.destinations.some((place) => !place)
  )
    return "请从地点候选中确认出发地和所有目的地。";
  const ids = input.destinations.map((place) => place!.place_id);
  if (new Set(ids).size !== ids.length) return "目的地重复了，请删除重复站点。";
  if (ids.length > 5) return "一次旅行最多安排 5 个目的地。";
  if (!input.start_date || !input.end_date) return "请选择出发和返程日期。";
  const days =
    (Date.parse(input.end_date) - Date.parse(input.start_date)) / 86400000 + 1;
  if (!Number.isFinite(days) || days < 1) return "返程日期不能早于出发日期。";
  if (days > 14) return "单次旅行最多 14 天，请调整日期。";
  if (ids.length > days)
    return "目的地数量超过旅行天数，请减少站点或增加天数。";
  if (
    !input.party ||
    input.party.adults < 1 ||
    input.party.adults > 20 ||
    input.party.children < 0 ||
    input.party.children > 20
  )
    return "请确认同行人数，成人至少 1 位，每类人数最多 20 位。";
  if (!input.style?.primary.trim()) return "请选择这趟旅行的主要风格。";
  return null;
}

export function parseTripBudget(raw: string): { value: number | null; error: string | null } {
  const normalized = raw.replace(/[,，\s]/g, "");
  if (!normalized) return { value: null, error: null };
  const value = Number(normalized);
  if (!Number.isFinite(value) || value <= 0) {
    return { value: null, error: "总预算请输入大于 0 的金额" };
  }
  return { value, error: null };
}
