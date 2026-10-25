import React from 'react';
import { AlertCircle, RefreshCw, RotateCcw } from 'lucide-react';
import { Button } from './Button';
import { cn } from '../../lib/utils';
import { type RequestFailure } from '../../lib/requestFailureMessage';


export const RecoveryAction: React.FC<{
  failure: RequestFailure;
  onRetry: () => void;
  className?: string;
}> = ({ failure, onRetry, className }) => {
  if (failure.recovery === 'none') return null;
  const reload = failure.recovery === 'reload';
  return (
    <Button
      variant="secondary"
      size="sm"
      data-testid="request-failure-action"
      onClick={reload ? () => window.location.reload() : onRetry}
      className={className}
    >
      {reload ? <RotateCcw size={14} aria-hidden /> : <RefreshCw size={14} aria-hidden />}
      {reload ? '刷新页面' : '重试'}
    </Button>
  );
};

export const RequestFailureNotice: React.FC<{
  title: string;
  failure: RequestFailure;
  onRetry: () => void;
  className?: string;
}> = ({ title, failure, onRetry, className }) => (
  <div
    role="alert"
    data-testid="request-failure-notice"
    data-recovery={failure.recovery}
    className={cn('rounded-card border border-warning/30 bg-warning/10 p-4', className)}
  >
    <div className="flex items-start gap-2">
      <AlertCircle size={16} className="mt-0.5 shrink-0 text-warning" aria-hidden />
      <div className="min-w-0">
        <p className="text-sm font-semibold text-ink">{title}</p>
        <p className="mt-1 break-words text-xs leading-relaxed text-ink-secondary">{failure.message}</p>
        <RecoveryAction failure={failure} onRetry={onRetry} className="mt-3" />
      </div>
    </div>
  </div>
);
