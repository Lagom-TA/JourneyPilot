import { Skeleton } from "../../components/ui/Skeleton";
import React from 'react';
export const PageSkeleton: React.FC = () => (<div data-testid="page-skeleton" className="archive-page" aria-label="正在打开页面">
    <div className="archive-layout">
      <div className="archive-rail"><Skeleton radius="label" tone="surface" className="h-20 w-40"/></div>
      <div className="archive-content divide-y divide-stroke/60">
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
