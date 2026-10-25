import { cn } from "../../../../lib/utils";
import { splitLabelledFact } from "../../model/tripDomains";
import { READOUT_LABEL } from "../../../../lib/typography";
export function TripFactReadout({ label, value }: {
    label: string;
    value: string;
}) {
    return (<div className="min-w-0">
      <dt className={cn(READOUT_LABEL, 'text-ink-muted')}>{label}</dt>
      <dd className="mt-1.5 break-words text-[15px] font-medium leading-6 text-ink">{value}</dd>
    </div>);
}
export function LabelledFactList({ facts, testId, }: {
    facts: readonly string[];
    testId?: string;
}) {
    return (<dl data-testid={testId} className="grid gap-x-8 sm:grid-cols-2">
      {facts.map((fact, index) => {
            const { label, value } = splitLabelledFact(fact);
            return (<div key={fact} className={cn('min-w-0 border-t border-stroke/60 py-3', index === 0 && 'border-t-0 pt-0', index === 1 && 'sm:border-t-0 sm:pt-0')}>
            {label && (<dt className={cn(READOUT_LABEL, 'text-chart')}>{label}</dt>)}
            <dd className="mt-1.5 break-words text-[15px] font-medium leading-6 text-ink">{value}</dd>
          </div>);
        })}
    </dl>);
}
