import React from 'react';
import { Search } from 'lucide-react';
import { ChartMark, type ChartMarkName } from './ChartMark';
import { Input } from './Input';
import { RequestFailureNotice } from './RequestFailureNotice';
import { Skeleton } from './Skeleton';
import { type RequestFailure } from '../../lib/requestFailureMessage';


export type SurfaceState =
  | { kind: 'loading' }
  | { kind: 'error'; title: string; failure: RequestFailure; onRetry: () => void }
  | { kind: 'search-miss'; line: string; hint?: string }
  | { kind: 'empty'; mark: ChartMarkName | null; line: string; hint?: string }
  | { kind: 'ready' };

interface PageShellProps {
  title: string;
  purpose?: string;
  readout?: React.ReactNode;
  actions?: React.ReactNode;
  navigation?: React.ReactNode;
  search?: {
    value: string;
    onChange: (value: string) => void;
    placeholder: string;
  };
  tabs?: React.ReactNode;
  state: SurfaceState;
  children?: React.ReactNode;
}

export const PageShell: React.FC<PageShellProps> = ({
  title,
  purpose,
  readout,
  actions,
  navigation,
  search,
  tabs,
  state,
  children,
}) => {
  return (
    <div className="archive-page">
      <div className="archive-layout">
        <header className="archive-rail">
          <h1 className="archive-title" aria-label={title}>
            <span>{title.slice(0, 2)}</span><span>{title.slice(2)}</span>
          </h1>
          {purpose && <p className="archive-note">{purpose}</p>}
          {navigation}
          {actions && <div className="archive-actions">{actions}</div>}
        </header>
        <div className="archive-content">
          {(search || readout) && <div className="archive-toolbar">
            {search && <Input value={search.value} onChange={(event) => search.onChange(event.target.value)} placeholder={search.placeholder} aria-label={search.placeholder} icon={<Search size={16} />} />}
            {readout && <span className="archive-readout">{readout}</span>}
          </div>}
          {tabs && <div className="archive-tabs">{tabs}</div>}
          <SurfaceBody state={state}>{children}</SurfaceBody>
        </div>
      </div>
    </div>
  );
};

const SurfaceBody: React.FC<{
  state: SurfaceState;
  children?: React.ReactNode;
}> = ({ state, children }) => {
  switch (state.kind) {
    case 'loading':
      return (
        <div data-testid="surface-loading" className="divide-y divide-stroke/60">
          {[0, 1, 2, 3].map((row) => (
            <div key={row} className="flex items-center justify-between gap-4 py-4">
              <div className="flex min-w-0 flex-1 flex-col gap-2">
                <Skeleton radius="label" className={row % 2 ? 'h-4 w-1/3' : 'h-4 w-1/2'} />
                <Skeleton radius="label" className="h-3 w-2/5" />
              </div>
              <Skeleton radius="label" className="h-3 w-20 flex-shrink-0" />
            </div>
          ))}
        </div>
      );

    case 'error':
      return (
        <RequestFailureNotice title={state.title} failure={state.failure} onRetry={state.onRetry} />
      );

    case 'search-miss':
      return (
        <div className="archive-empty">
          <p className="text-base text-ink-secondary">{state.line}</p>
          {state.hint && <p className="mt-1.5 text-xs text-ink-muted">{state.hint}</p>}
        </div>
      );

    case 'empty':
      return (
        <div className="archive-empty">
          {state.mark && <ChartMark mark={state.mark} size={104} className="mb-5" />}
          <p className="text-base text-ink">{state.line}</p>
          {state.hint && <p className="mt-1.5 text-xs text-ink-secondary">{state.hint}</p>}
        </div>
      );

    case 'ready':
      return <>{children}</>;
  }
};
