import React from 'react';
import { Search } from 'lucide-react';
import { m } from 'motion/react';
import { cn } from '../../lib/utils';
import { ChartMark, type ChartMarkName } from './ChartMark';
import { Neatline } from './Neatline';
import { Input } from './Input';
import { RequestFailureNotice } from './RequestFailureNotice';
import { Skeleton } from './Skeleton';
import { staggerContainer, staggerItem } from '../../lib/motion';
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
  search?: {
    value: string;
    onChange: (value: string) => void;
    placeholder: string;
  };
  tabs?: React.ReactNode;
  state: SurfaceState;
  children?: React.ReactNode;
}

export const PAGE_COLUMN = 'mx-auto w-full max-w-5xl';

export const PAGE_GUTTER = 'px-6';

export const PageShell: React.FC<PageShellProps> = ({
  title,
  purpose,
  readout,
  actions,
  search,
  tabs,
  state,
  children,
}) => {
  const steps = 2 + (search ? 1 : 0) + (tabs ? 1 : 0);

  return (
    <m.div
      className="flex h-full flex-col overflow-hidden"
      variants={staggerContainer(steps)}
      initial="hidden"
      animate="visible"
    >
      <div className={cn('flex-shrink-0 pb-4 pt-6', PAGE_GUTTER)}>
        <div className={PAGE_COLUMN}>
          <m.div
            variants={staggerItem}
            className="flex min-w-0 flex-wrap items-start justify-between gap-3"
          >
            <div className="min-w-0">
              <h1 className="font-display text-[28px] font-semibold leading-tight text-ink">{title}</h1>
              {purpose && <p className="mt-1.5 text-[13px] text-ink-secondary">{purpose}</p>}
            </div>
            <div className="flex flex-shrink-0 items-center gap-3">
              {/* 混合中文读数不加拉丁标签字距，避免量词间距被拉宽。 */}
              {readout && <span className="text-[11px] tabular-nums text-ink-muted">{readout}</span>}
              {actions}
            </div>
          </m.div>

          {search && (
            <m.div variants={staggerItem} className="mt-4">
              <Input
                value={search.value}
                onChange={(event) => search.onChange(event.target.value)}
                placeholder={search.placeholder}
                icon={<Search size={15} />}
              />
            </m.div>
          )}

          {tabs && (
            <m.div variants={staggerItem} className="mt-3">
              {tabs}
            </m.div>
          )}
        </div>
      </div>

      <div className={cn('flex flex-1 flex-col overflow-y-auto pb-6', PAGE_GUTTER)}>
        <m.div variants={staggerItem} className={cn('flex flex-1 flex-col', PAGE_COLUMN)}>
          {/* 负外边距抵消内容内边距，使正文与标题左缘对齐。 */}
          <div className="relative -mx-6 flex flex-1 flex-col border border-stroke bg-panel px-6 py-7">
            <Neatline />
            <div className="relative z-[1] flex flex-1 flex-col">
              <SurfaceBody state={state}>{children}</SurfaceBody>
            </div>
          </div>
        </m.div>
      </div>
    </m.div>
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
        <div className="flex flex-1 flex-col items-center justify-center py-16 text-center">
          <p className="text-base text-ink-secondary">{state.line}</p>
          {state.hint && <p className="mt-1.5 text-xs text-ink-muted">{state.hint}</p>}
        </div>
      );

    case 'empty':
      return (
        <div className="flex flex-1 flex-col items-center justify-center py-16 text-center">
          {state.mark && <ChartMark mark={state.mark} size={104} className="mb-5" />}
          <p className="text-base text-ink">{state.line}</p>
          {state.hint && <p className="mt-1.5 text-xs text-ink-secondary">{state.hint}</p>}
        </div>
      );

    case 'ready':
      return <>{children}</>;
  }
};
