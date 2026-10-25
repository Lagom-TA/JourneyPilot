import React from 'react';
import { Button } from './Button';

/* React 的错误边界生命周期仅由 class 组件提供。 */
interface LazyViewBoundaryProps {
  children: React.ReactNode;
  resetKey?: React.Key;
}

interface LazyViewBoundaryState {
  failed: boolean;
}

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
      return (
        <div className="flex h-full items-center justify-center bg-bg p-6">
          <div className="max-w-[52ch] rounded-card border border-stroke bg-panel p-6 text-center shadow-sm">
            <p className="text-sm leading-relaxed text-ink-secondary">
              这个页面没能加载出来，通常是网络中断导致的。
            </p>
            <div className="mt-4 flex justify-center">
              <Button variant="secondary" size="sm" onClick={this.handleReload}>
                重新加载
              </Button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
