import { ChevronDown } from "lucide-react";
import { cn } from "../../../../lib/utils";
import { type ContextReport, type ContextReportSection, type ContextReportSectionKey } from "../../types/context";
import React, { useId, useState } from 'react';
const SECTION_LABEL: Record<ContextReportSectionKey, string> = {
    hard: '硬约束',
    preference: '偏好',
    reference: '参考级背景',
};
const COLLAPSED_ITEM_LIMIT = 6;
function visibleSections(sections: ContextReportSection[], budget: number): ContextReportSection[] {
    const out: ContextReportSection[] = [];
    let remaining = budget;
    for (const section of sections) {
        if (remaining <= 0)
            break;
        const items = section.items.slice(0, remaining);
        remaining -= items.length;
        out.push({ ...section, items });
    }
    return out;
}
export const ContextLens: React.FC<{
    report: ContextReport;
}> = ({ report }) => {
    const [expanded, setExpanded] = useState(false);
    const listId = useId();
    const total = report.sections.reduce((count, section) => count + section.items.length, 0);
    const foldable = total > COLLAPSED_ITEM_LIMIT;
    const collapsed = foldable && !expanded;
    const shown = collapsed ? visibleSections(report.sections, COLLAPSED_ITEM_LIMIT) : report.sections;
    return (<div data-testid="context-lens" className="flex max-w-[320px] flex-col gap-3 p-4">

      <span className="text-[13px] font-semibold text-ink">本次参考的信息</span>
      <div id={listId} className="flex flex-col gap-3">
        {shown.map((section) => (<div key={section.key} className="flex flex-col gap-1.5">
            <div className="flex items-baseline gap-1.5">
              <span className="text-[11px] font-semibold text-ink">{SECTION_LABEL[section.key]}</span>

              {section.key === 'reference' && (<span className="text-[11px] text-ink-muted">参考，不是要求</span>)}
            </div>
            <ul className="flex flex-col gap-1.5">
              {section.items.map((item) => (<li key={`${section.key}:${item}`} className="rounded-card bg-surface px-3 py-2 text-xs leading-relaxed text-ink-secondary">
                  {item}
                </li>))}
            </ul>
          </div>))}
      </div>
      {foldable && (<button type="button" data-testid="context-lens-toggle" aria-expanded={expanded} aria-controls={listId} onClick={() => setExpanded((current) => !current)} className="-ml-2 inline-flex min-h-9 items-center gap-1 self-start rounded-card px-2 text-[11px] font-semibold text-ink-secondary transition-colors hover:bg-highlight hover:text-ink">
          {expanded ? '收起' : `展开全部 ${total} 条`}
          <ChevronDown size={13} aria-hidden className={cn('transition-transform', expanded && 'rotate-180')}/>
        </button>)}
      {report.compaction.triggered && (<p className="rounded-card bg-surface px-3 py-2 text-[11px] leading-relaxed text-ink-secondary">
          较早的对话已整理，旅行重点和已明确的规划约束会继续沿用。
        </p>)}
    </div>);
};
