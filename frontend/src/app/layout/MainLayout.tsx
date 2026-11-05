import { BookOpen, ChevronRight, Map, PanelLeftClose, PanelLeftOpen, Plus, SlidersHorizontal } from 'lucide-react';
import { AnimatePresence, m } from 'motion/react';
import { cn } from '../../lib/utils';
import { useApp } from '../state/AppContext';
import { type ActiveView } from '../state/state';
import { useIsMobileViewport } from '../../hooks/useMediaQuery';
import { useOverlayDismiss } from '../../hooks/useOverlayDismiss';
import { BrandMark, BrandWordmark } from '../components/BrandMark';
import { useStartNewTrip } from '../session/useStartNewTrip';
import { PREFERENCE_LINKS } from '../components/PreferenceSectionNav';
import { duration, easing } from '../../lib/motion';
import { getViewHref } from '../../lib/viewHref';
import React from 'react';

interface MainLayoutProps {
  children: React.ReactNode;
}

const PREFERENCE_VIEWS: ActiveView[] = ['user-preferences', 'presets', 'knowledge-base'];

export const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
  const { state, dispatch } = useApp();
  const beginNewTrip = useStartNewTrip();
  const isMobile = useIsMobileViewport();
  const drawerOpen = isMobile && !state.sidebarCollapsed;
  const sidebarRef = React.useRef<HTMLElement>(null);
  const mainRef = React.useRef<HTMLElement>(null);
  const closeSidebar = React.useCallback(() => dispatch({ type: 'SET_SIDEBAR_COLLAPSED', payload: true }), [dispatch]);
  useOverlayDismiss({ open: drawerOpen, onDismiss: closeSidebar, panelRef: sidebarRef });

  React.useLayoutEffect(() => {
    sidebarRef.current?.toggleAttribute('inert', isMobile && state.sidebarCollapsed);
    mainRef.current?.toggleAttribute('inert', drawerOpen);
  }, [drawerOpen, isMobile, state.sidebarCollapsed]);

  const changeView = React.useCallback((view: ActiveView) => {
    dispatch({ type: 'SET_ACTIVE_VIEW', payload: view });
    if (isMobile) closeSidebar();
  }, [closeSidebar, dispatch, isMobile]);

  const startNewTrip = React.useCallback(() => {
    beginNewTrip();
    if (isMobile) closeSidebar();
  }, [beginNewTrip, closeSidebar, isMobile]);

  const keepFocusInDrawer = (event: React.KeyboardEvent<HTMLElement>) => {
    if (!drawerOpen || event.key !== 'Tab') return;
    const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), [tabindex="0"]')]
      .filter((node) => node.offsetParent !== null);
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && (document.activeElement === first || document.activeElement === sidebarRef.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const navLink = (view: ActiveView, label: string, icon: React.ReactNode, mobile = false) => {
    const active = view === 'chat'
      ? state.activeView === 'chat'
      : view === 'user-preferences'
        ? PREFERENCE_VIEWS.includes(state.activeView)
        : state.activeView === view;
    const content = (
      <>
        {icon}
        <span>{label}</span>
        {mobile && <ChevronRight size={15} className="ml-auto opacity-45" aria-hidden />}
      </>
    );
    const className = cn(mobile ? 'mobile-nav-link' : 'desktop-nav-link', active && 'is-active');
    if (view === 'chat') {
      return <a key={`${mobile ? 'mobile' : 'desktop'}-${view}`} href={getViewHref('chat')} aria-current={active ? 'page' : undefined} className={className} onClick={(event) => { event.preventDefault(); startNewTrip(); }}>{content}</a>;
    }
    return <a key={`${mobile ? 'mobile' : 'desktop'}-${view}`} href={getViewHref(view)} aria-current={active ? 'page' : undefined} className={className} onClick={(event) => { event.preventDefault(); changeView(view); }}>{content}</a>;
  };

  return (
    <div className="app-shell paper-grain">
      <header aria-hidden={drawerOpen || undefined} className="app-topbar">
        <a href={getViewHref('chat')} className="app-brand" aria-label="JourneyPilot 新旅行" onClick={(event) => { event.preventDefault(); startNewTrip(); }}>
          <BrandMark size={27} />
          <BrandWordmark height={16} className="app-brand-word" />
        </a>
        <nav className="desktop-main-nav" aria-label="主导航">
          {navLink('chat', '新旅行', <Plus size={15} aria-hidden />)}
          {navLink('trips', '我的行程', <Map size={15} aria-hidden />)}
          {navLink('user-preferences', '偏好与资料', <SlidersHorizontal size={15} aria-hidden />)}
        </nav>
        <button
          type="button"
          data-testid="sidebar-open"
          aria-label="打开导航"
          aria-controls="app-navigation"
          aria-expanded={drawerOpen}
          tabIndex={drawerOpen ? -1 : 0}
          onClick={() => dispatch({ type: 'SET_SIDEBAR_COLLAPSED', payload: false })}
          className="mobile-nav-opener"
        >
          <PanelLeftOpen size={19} aria-hidden />
        </button>
      </header>

      <main ref={mainRef} className="app-main">
        {children}
      </main>

      <AnimatePresence>
        {drawerOpen && (
          <m.div
            data-testid="sidebar-scrim"
            aria-hidden
            className="mobile-nav-scrim"
            onClick={closeSidebar}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1, transition: { duration: duration.base, ease: easing.decelerate } }}
            exit={{ opacity: 0, transition: { duration: duration.fast, ease: easing.accelerate } }}
          />
        )}
      </AnimatePresence>
      <aside
        id="app-navigation"
        ref={sidebarRef}
        data-testid="app-sidebar"
        role={drawerOpen ? 'dialog' : undefined}
        aria-modal={drawerOpen || undefined}
        aria-label="主导航"
        tabIndex={drawerOpen ? -1 : undefined}
        onKeyDown={keepFocusInDrawer}
        className={cn('mobile-navigation-drawer', drawerOpen ? 'is-open' : 'is-closed')}
      >
        <div className="mobile-drawer-heading">
          <div className="flex items-center gap-2.5"><BrandMark size={24} /><BrandWordmark height={14} /></div>
          <button type="button" aria-label="收起侧栏" onClick={closeSidebar} className="mobile-drawer-close"><PanelLeftClose size={18} /></button>
        </div>
        <nav className="mobile-drawer-nav" aria-label="旅行导航">
          {navLink('chat', '新旅行', <Plus size={17} aria-hidden />, true)}
          {navLink('trips', '我的行程', <BookOpen size={17} aria-hidden />, true)}
          <p className="mobile-drawer-section-label">偏好与资料</p>
          <div className="mobile-preference-links">
            {PREFERENCE_LINKS.map((item) => (
              <a key={item.view} href={getViewHref(item.view)} className={cn('mobile-nav-link', state.activeView === item.view && 'is-active')} onClick={(event) => { event.preventDefault(); changeView(item.view); }}>
                <span>{item.label}</span><ChevronRight size={15} className="ml-auto opacity-45" />
              </a>
            ))}
          </div>
        </nav>
      </aside>
    </div>
  );
};
