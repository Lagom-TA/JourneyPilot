import { useApp } from "../../state/AppContext";
import { type ActiveView } from "../../state/state";
import { SidebarSearch } from "./SidebarSearch";
import { ConversationList } from "../../../features/chat/components/ConversationList";
import { SidebarNav } from "./SidebarNav";
import { Plus, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Button } from "../../../components/ui/Button";
import { BrandMark, BrandWordmark } from "../../components/BrandMark";
import { Tooltip } from "../../../components/ui/Tooltip";
import { cn } from "../../../lib/utils";
import { useSessionManager } from "../../session/useSessionManager";
import { useIsMobileViewport } from "../../../hooks/useMediaQuery";
import { RAIL_GUTTER, RAIL_LABEL, RAIL_SLOT, RAIL_SLOT_INDENT } from "./rail";
import React, { useState } from 'react';
export const Sidebar: React.FC = () => {
    const { state, dispatch, activeStreamAbortRef } = useApp();
    const { setLastSession } = useSessionManager();
    const [searchQuery, setSearchQuery] = useState('');
    const collapsed = state.sidebarCollapsed;
    const isMobile = useIsMobileViewport();
    const searchInputRef = React.useRef<HTMLInputElement>(null);
    const handleNewChat = () => {
        if (activeStreamAbortRef.current) {
            activeStreamAbortRef.current.abort();
            activeStreamAbortRef.current = null;
        }
        dispatch({ type: 'CLEAR_CHAT' });
        setLastSession(null);
        dispatch({ type: 'SET_ACTIVE_VIEW', payload: 'chat' });
        if (isMobile)
            dispatch({ type: 'SET_SIDEBAR_COLLAPSED', payload: true });
    };
    const sidebarToggleLabel = collapsed ? '展开侧栏' : '收起侧栏';
    const handleNavChange = (view: ActiveView) => {
        dispatch({ type: 'SET_ACTIVE_VIEW', payload: view });
        if (isMobile)
            dispatch({ type: 'SET_SIDEBAR_COLLAPSED', payload: true });
    };
    const handleExpandAndFocusSearch = () => {
        dispatch({ type: 'SET_SIDEBAR_COLLAPSED', payload: false });
        requestAnimationFrame(() => {
            searchInputRef.current?.focus();
        });
    };
    return (<div className="flex h-full w-full flex-col">

      <div className={cn('relative flex items-center pb-2 pt-3', RAIL_GUTTER)}>
        {!collapsed && (<div className={cn('flex min-w-0 flex-1 items-center overflow-hidden', RAIL_SLOT_INDENT)}>
            <span className={RAIL_SLOT}>
              <BrandMark size={22}/>
            </span>

            <BrandWordmark height={13} className="shrink-0"/>
          </div>)}

        <Tooltip content={sidebarToggleLabel} position="right" disabled={!collapsed}>
          <Button variant="icon" aria-label={sidebarToggleLabel} className={cn('!h-10 !w-10 shrink-0', collapsed && 'ml-1.5')} onClick={() => dispatch({ type: 'TOGGLE_SIDEBAR' })}>
            {collapsed ? <PanelLeftOpen size={18}/> : <PanelLeftClose size={18}/>}
          </Button>
        </Tooltip>
      </div>

      <div className="mb-3 border-t border-stroke/60"/>


      <div className={cn('pb-3', RAIL_GUTTER)}>
        <Tooltip content="新建行程" position="right" disabled={!collapsed} className="w-full">
          <Button variant="primary" size="md" onClick={handleNewChat} className="touch-row relative flex h-10 w-full items-center overflow-hidden !justify-start !gap-0 !pl-1.5 !pr-2">
            <span className={RAIL_SLOT}>
              <Plus size={18}/>
            </span>
            <span className={cn(RAIL_LABEL, 'text-sm', collapsed ? 'opacity-0' : 'opacity-100')}>
              新建行程
            </span>
          </Button>
        </Tooltip>
      </div>


      <div className={cn('pb-3', RAIL_GUTTER)}>
        <SidebarSearch value={searchQuery} onChange={setSearchQuery} collapsed={collapsed} inputRef={searchInputRef} onExpandAndFocus={handleExpandAndFocusSearch}/>
      </div>


      <div data-testid="sidebar-conversations" className={cn('min-h-0 flex-1 overflow-y-auto', RAIL_GUTTER)}>
        {!collapsed && <ConversationList searchQuery={searchQuery}/>}
      </div>

      <SidebarNav activeView={state.activeView} onChange={handleNavChange} collapsed={collapsed}/>
    </div>);
};
