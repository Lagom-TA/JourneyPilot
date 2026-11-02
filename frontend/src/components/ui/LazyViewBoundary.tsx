import React from 'react';
import { Button } from './Button';

/* React 的错误边界生命周期仅由 class 组件提供。 */
interface LazyViewBoundaryProps {
  children: React.ReactNode;
  resetKey?: React.Key;
  /* 失败提示只描述当前可确认的状态，不对未知异常断言原因。 */
  message?: string;
  retryLabel?: string;
  /* 局部边界用：失败时用调用方提供的界面替代默认整页提示。 */
  fallback?: React.ReactNode;
}

interface LazyViewBoundaryState {
  failed: boolean;
}

const DEFAULT_FAILURE_MESSAGE = '这个页面没能加载出来。';
const DEFAULT_RETRY_LABEL = '重新加载';

export class LazyViewBoundary extends React.Component<
  LazyViewBoundaryProps,
  LazyViewBoundaryState
> {
  state: LazyViewBoundaryState = { failed: false };

  static getDerivedStateFromError(): LazyViewBoundaryState {
    return { failed: true };
  }

  componentDidUpdate(prevProps: LazyViewBoundaryProps) {
    if (this.state.failed && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ failed: false });
    }
  }

  private handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.failed) {
      if (this.props.fallback !== undefined) {
        return this.props.fallback;
      }
      return (
        <div data-testid="lazy-view-failure" role="alert" className="flex h-full items-center justify-center bg-bg p-6">
          <div className="max-w-[52ch] rounded-card border border-stroke bg-panel p-6 text-center shadow-sm">
            <p className="text-sm leading-relaxed text-ink-secondary">
              {this.props.message ?? DEFAULT_FAILURE_MESSAGE}
            </p>
            <div className="mt-4 flex justify-center">
              <Button variant="secondary" size="sm" onClick={this.handleReload}>
                {this.props.retryLabel ?? DEFAULT_RETRY_LABEL}
              </Button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
