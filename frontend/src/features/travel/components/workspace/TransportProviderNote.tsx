import { Info } from "lucide-react";
import { cn } from "../../../../lib/utils";
import { Popover } from "../../../../components/ui/Popover";
export const FLIGHT_PROVIDER_NOTE_LABEL = '班次数据来源';
export function TransportProviderNote({ detail }: {
    detail: string;
}) {
    return (<Popover placement="top-end" portal testId="transport-provider-note-detail" className="p-3" trigger={({ ref, open, toggle }) => (<button ref={ref} type="button" data-testid="transport-provider-note" onClick={toggle} aria-label={`查看${FLIGHT_PROVIDER_NOTE_LABEL}说明`} aria-expanded={open} aria-haspopup="true" className={cn('inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-card border border-stroke bg-panel text-ink-secondary transition-[color,border-color,background-color] duration-fast ease-standard', 'hover:border-accent/35 hover:bg-accent-soft hover:text-accent', open && 'border-accent/40 bg-accent-soft text-accent')}>
          <Info size={12} strokeWidth={2.25} aria-hidden="true"/>
        </button>)}>
      {() => (<div className="text-left text-xs leading-relaxed text-ink-secondary">
          <div className="flex items-center gap-1.5 text-ink">
            <Info size={14} aria-hidden="true"/>
            <p className="font-semibold">{FLIGHT_PROVIDER_NOTE_LABEL}</p>
          </div>
          <p className="mt-1">{detail}</p>
        </div>)}
    </Popover>);
}
