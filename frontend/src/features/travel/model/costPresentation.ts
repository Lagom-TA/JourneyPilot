import { type PublicDeliveryBundle } from '../types/delivery';

type CostSummary = NonNullable<PublicDeliveryBundle['report_projection']['document']>['cost_summary'];

const money = new Intl.NumberFormat('zh-CN', {
  style: 'currency',
  currency: 'CNY',
  maximumFractionDigits: 0,
});

export function formatTripCostSummary(cost: CostSummary | null | undefined): string | null {
  if (!cost) return null;
  if (cost.estimated_total_cny != null) return `全程约 ${money.format(cost.estimated_total_cny)}`;
  if (cost.known_subtotal_cny != null) return `已列费用约 ${money.format(cost.known_subtotal_cny)}`;
  return null;
}
