import { CalendarClock, PenLine } from "lucide-react";
import { type EvidenceBasis } from "../../types/itinerary";
export const PUBLIC_REFERENCE_LABEL = '公开资料整理';
export const PUBLIC_REFERENCE_HINT = '由规划模型依据公开资料写入，未附来源链接';
export const REFERENCE_SERVICE_LABEL = '参考班次';
export const REFERENCE_SERVICE_HINT = '来自供应商的真实班次，但未对你的出行日期确认';
const STATED: Partial<Record<EvidenceBasis, {
    label: string;
    hint: string;
    icon: typeof PenLine;
}>> = {
    public_reference: {
        label: PUBLIC_REFERENCE_LABEL,
        hint: PUBLIC_REFERENCE_HINT,
        icon: PenLine,
    },
    reference_service: {
        label: REFERENCE_SERVICE_LABEL,
        hint: REFERENCE_SERVICE_HINT,
        icon: CalendarClock,
    },
};
export function EvidenceBasisChip({ basis }: {
    basis: EvidenceBasis | null;
}) {
    const stated = basis ? STATED[basis] : undefined;
    if (!basis || !stated)
        return null;
    const Icon = stated.icon;
    return (<span role="note" data-testid="entity-evidence-basis" data-evidence-basis={basis} title={stated.hint} aria-label={stated.hint} className="mt-2 inline-flex max-w-full items-center gap-1 rounded-label bg-surface px-1.5 py-0.5 text-[11px] font-medium leading-5 text-ink-muted">
      <Icon size={11} className="shrink-0" aria-hidden/>
      <span className="min-w-0 break-words">{stated.label}</span>
    </span>);
}
