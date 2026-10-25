import { cn } from "../../lib/utils";
import { PAGE_COLUMN, PAGE_GUTTER } from "../../components/ui/PageShell";
import { Skeleton } from "../../components/ui/Skeleton";
import React from 'react';
export const PageSkeleton: React.FC = () => (<div data-testid="page-skeleton" className="flex h-full flex-col overflow-hidden">
    <div className={cn('flex-shrink-0 pb-4 pt-6', PAGE_GUTTER)}>
      <div className={PAGE_COLUMN}>
        <Skeleton radius="label" tone="surface" className="h-6 w-40"/>
        <Skeleton radius="label" tone="surface" className="mt-2 h-3 w-56"/>

        <div className="mt-4 h-11 border-b border-stroke"/>
      </div>
    </div>

    <div className={cn('flex-1 overflow-hidden pb-6', PAGE_GUTTER)}>
      <div className={cn(PAGE_COLUMN, 'divide-y divide-stroke/60')}>
        {[0, 1, 2, 3].map((row) => (<div key={row} className="flex items-center justify-between gap-4 py-4">
            <div className="flex min-w-0 flex-1 flex-col gap-2">
              <Skeleton radius="label" tone="surface" className={row % 2 ? 'h-4 w-1/3' : 'h-4 w-1/2'}/>
              <Skeleton radius="label" tone="surface" className="h-3 w-2/5"/>
            </div>
            <Skeleton radius="label" tone="surface" className="h-3 w-20 flex-shrink-0"/>
          </div>))}
      </div>
    </div>
  </div>);
