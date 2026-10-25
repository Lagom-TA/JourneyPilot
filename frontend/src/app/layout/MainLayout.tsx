import { PanelLeftOpen } from "lucide-react";
import { cn } from "../../lib/utils";
import { useApp } from "../state/AppContext";
import { useIsMobileViewport } from "../../hooks/useMediaQuery";
import { useOverlayDismiss } from "../../hooks/useOverlayDismiss";
import { Sidebar } from "./sidebar/Sidebar";
import { BrandMark, BrandWordmark } from "../components/BrandMark";
import React from 'react';
interface MainLayoutProps {
    children: React.ReactNode;
}
export const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
    const { state, dispatch } = useApp();
    const { sidebarCollapsed } = state;
    const isMobile = useIsMobileViewport();
    const drawerOpen = isMobile && !sidebarCollapsed;
    const sidebarRef = React.useRef<HTMLElement>(null);
    const mainRef = React.useRef<HTMLElement>(null);
    const closeSidebar = () => dispatch({ type: 'SET_SIDEBAR_COLLAPSED', payload: true });
    useOverlayDismiss({ open: drawerOpen, onDismiss: closeSidebar, panelRef: sidebarRef });
    React.useLayoutEffect(() => {
        sidebarRef.current?.toggleAttribute('inert', isMobile && sidebarCollapsed);
        mainRef.current?.toggleAttribute('inert', drawerOpen);
    }, [drawerOpen, isMobile, sidebarCollapsed]);
    const keepFocusInDrawer = (event: React.KeyboardEvent<HTMLElement>) => {
        if (!drawerOpen || event.key !== 'Tab')
            return;
        const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), [tabindex="0"]')].filter((node) => node.offsetParent !== null);
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (!first || !last)
            return;
        if (event.shiftKey && (document.activeElement === first || document.activeElement === sidebarRef.current)) {
            event.preventDefault();
            last.focus();
        }
        else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    };
    return (<div className="paper-grain relative flex h-dvh w-full overflow-hidden bg-bg">
      <header aria-hidden={drawerOpen || undefined} className="absolute inset-x-0 top-0 z-10 flex h-14 items-center justify-center border-b border-stroke/70 bg-panel lg:hidden">
        <button type="button" data-testid="sidebar-open" aria-label="打开导航" aria-controls="app-navigation" aria-expanded={drawerOpen} tabIndex={drawerOpen ? -1 : 0} onClick={() => dispatch({ type: 'SET_SIDEBAR_COLLAPSED', payload: false })} className="absolute left-3 flex h-11 w-11 items-center justify-center rounded-card text-ink-secondary transition-colors hover:bg-surface hover:text-ink">
          <PanelLeftOpen size={18} aria-hidden="true"/>
        </button>
        <div className="flex items-center gap-2.5"><BrandMark size={18}/><BrandWordmark height={12}/></div>
      </header>

      {drawerOpen && (<div data-testid="sidebar-scrim" aria-hidden="true" className="fixed inset-0 z-20 bg-ink/25 backdrop-blur-sm lg:hidden" onClick={closeSidebar}/>)}

      <aside id="app-navigation" ref={sidebarRef} data-testid="app-sidebar" role={drawerOpen ? 'dialog' : undefined} aria-modal={drawerOpen || undefined} aria-label="主导航" tabIndex={drawerOpen ? -1 : undefined} onKeyDown={keepFocusInDrawer} className={cn('absolute left-0 top-0 h-full flex-shrink-0 lg:relative', 'transition-[transform,width] duration-slow ease-standard', 'z-30 overflow-hidden bg-panel lg:z-10', 'shadow-[1px_0_0_rgb(var(--color-stroke-rgb)),4px_0_24px_rgba(32,33,36,0.04)]', sidebarCollapsed ? '-translate-x-full lg:translate-x-0 !w-[68px]' : 'translate-x-0 !w-[280px]')}>
        <Sidebar />
      </aside>

      <main ref={mainRef} className="relative z-0 flex h-full min-w-0 flex-1 flex-col overflow-hidden pt-14 lg:pt-0">
        {children}
      </main>
    </div>);
};
