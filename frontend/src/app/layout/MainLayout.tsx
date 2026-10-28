import { BookOpen, ChevronRight, Compass, Map, PanelLeftClose, PanelLeftOpen, Plus, SlidersHorizontal } from 'lucide-react';
import { AnimatePresence, m } from 'motion/react';
import { cn } from '../../lib/utils';
import { useApp } from '../state/AppContext';
import { type ActiveView } from '../state/state';
import { useIsMobileViewport } from '../../hooks/useMediaQuery';
import { useOverlayDismiss } from '../../hooks/useOverlayDismiss';
import { BrandMark, BrandWordmark } from '../components/BrandMark';
import { useSessionManager } from '../session/useSessionManager';
import { duration, easing } from '../../lib/motion';
import React from 'react';

interface MainLayoutProps {
  children: React.ReactNode;
}

const PREFERENCE_VIEWS: ActiveView[] = ['user-preferences', 'presets', 'knowledge-base'];

const PREFERENCE_LINKS: Array<{ view: ActiveView; label: string }> = [
  { view: 'user-preferences', label: '我的偏好' },
  { view: 'presets', label: '旅行风格' },
  { view: 'knowledge-base', label: '资料来源' },
];

export const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
  const { state, dispatch, activeStreamAbortRef } = useApp();
  const { setLastSession } = useSessionManager();
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
    activeStreamAbortRef.current?.abort();
    activeStreamAbortRef.current = null;
    dispatch({ type: 'CLEAR_CHAT' });
    setLastSession(null);
    const url = new URL(window.location.href);
    url.searchParams.delete('session_id');
    url.searchParams.delete('run_id');
    url.searchParams.set('view', 'chat');
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    changeView('chat');
  }, [activeStreamAbortRef, changeView, dispatch, setLastSession]);

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
      return <a key={`${mobile ? 'mobile' : 'desktop'}-${view}`} href="/?view=chat" aria-current={active ? 'page' : undefined} className={className} onClick={(event) => { event.preventDefault(); startNewTrip(); }}>{content}</a>;
    }
    return <a key={`${mobile ? 'mobile' : 'desktop'}-${view}`} href={`/?view=${view}`} aria-current={active ? 'page' : undefined} className={className} onClick={(event) => { event.preventDefault(); changeView(view); }}>{content}</a>;
  };

  const preferenceActive = PREFERENCE_VIEWS.includes(state.activeView);

  return (
    <div className="app-shell paper-grain">
      <header aria-hidden={drawerOpen || undefined} className="app-topbar">
        <a href="/?view=chat" className="app-brand" aria-label="JourneyPilot 新旅行" onClick={(event) => { event.preventDefault(); startNewTrip(); }}>
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

      {preferenceActive && (
        <nav className="preference-section-nav" aria-label="偏好与资料分类">
          <div>
            {PREFERENCE_LINKS.map((item) => (
              <a
                key={item.view}
                href={`/?view=${item.view}`}
                aria-current={state.activeView === item.view ? 'page' : undefined}
                className={cn(state.activeView === item.view && 'is-active')}
                onClick={(event) => { event.preventDefault(); changeView(item.view); }}
              >{item.label}</a>
            ))}
          </div>
        </nav>
      )}

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
          <p>旅行</p>
          {navLink('chat', '新旅行', <Plus size={17} aria-hidden />, true)}
          {navLink('trips', '我的行程', <BookOpen size={17} aria-hidden />, true)}
          <p className="mobile-drawer-section-label">你的旅行偏好</p>
          {navLink('user-preferences', '偏好与资料', <Compass size={17} aria-hidden />, true)}
          <div className="mobile-preference-links">
            {[...PREFERENCE_LINKS].reverse().map((item) => (
              <a key={item.view} href={`/?view=${item.view}`} className={cn('mobile-nav-link', state.activeView === item.view && 'is-active')} onClick={(event) => { event.preventDefault(); changeView(item.view); }}>
                <span>{item.label}</span><ChevronRight size={15} className="ml-auto opacity-45" />
              </a>
            ))}
          </div>
        </nav>
        <p className="mobile-drawer-footnote">让旅行更简单，更有意义。</p>
      </aside>
    </div>
  );
};
