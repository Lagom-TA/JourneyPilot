import { Popover } from "../../../../components/ui/Popover";
import { Tooltip } from "../../../../components/ui/Tooltip";
import { HALLMARK_REGISTRY } from "./registry";
import { type ContextReport } from "../../types/context";
import { type CostLedgerView } from "../../model/costLedger";
import React, { useState } from 'react';
type HallmarkProps = {
    glyph: 'context';
    data: ContextReport | null | undefined;
} | {
    glyph: 'cost';
    data: CostLedgerView | null | undefined;
};
const HallmarkTrigger: React.FC<{
    symbol: string;
    label: string;
    triggerRef: React.Ref<HTMLButtonElement>;
    open: boolean;
    toggle: () => void;
    testId: string;
}> = ({ symbol, label, triggerRef, open, toggle, testId }) => {
    const [hovered, setHovered] = useState(false);
    const lit = open || hovered;
    return (<button ref={triggerRef} type="button" data-testid={testId} aria-label={label} aria-expanded={open} onClick={toggle} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)} className="flex h-6 w-6 items-center justify-center leading-none transition-[color,opacity] duration-fast ease-standard" style={{
            fontSize: '12px',
            color: lit ? 'var(--color-accent)' : 'var(--color-ink-muted)',
            opacity: lit ? 1 : 0.45,
        }}>

      <span aria-hidden>{symbol}</span>
    </button>);
};
export const Hallmark: React.FC<HallmarkProps> = (props) => {
    if (!props.data)
        return null;
    const entry = props.glyph === 'context' ? HALLMARK_REGISTRY.context : HALLMARK_REGISTRY.cost;
    const { symbol, ariaLabel } = entry;
    const { blurb, body } = props.glyph === 'context'
        ? {
            blurb: HALLMARK_REGISTRY.context.blurb(props.data),
            body: HALLMARK_REGISTRY.context.render(props.data),
        }
        : {
            blurb: HALLMARK_REGISTRY.cost.blurb(props.data),
            body: HALLMARK_REGISTRY.cost.render(props.data),
        };
    return (<Popover placement="bottom-end" trigger={({ ref, open, toggle }) => (<Tooltip content={blurb} position="left" disabled={open}>
          <HallmarkTrigger symbol={symbol} label={ariaLabel} triggerRef={ref} open={open} toggle={toggle} testId={`hallmark-${props.glyph}`}/>
        </Tooltip>)}>
      {body}
    </Popover>);
};
