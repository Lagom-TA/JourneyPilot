import { cn } from "../../../lib/utils";
import { type ActiveView } from "../../state/state";
import { Tooltip } from "../../../components/ui/Tooltip";
import { BookOpen, Compass, Sliders } from "lucide-react";
import { RAIL_GUTTER, RAIL_LABEL, RAIL_SLOT, RAIL_SLOT_INDENT } from "./rail";
import React from 'react';
interface SidebarNavProps {
    activeView: ActiveView;
    onChange: (view: ActiveView) => void;
    collapsed?: boolean;
}
const navItems: Array<{
    view: ActiveView;
    icon: React.ReactNode;
    label: string;
}> = [
    { view: 'knowledge-base', icon: <BookOpen size={18}/>, label: '资料来源' },
    { view: 'presets', icon: <Compass size={18}/>, label: '旅行风格' },
    { view: 'user-preferences', icon: <Sliders size={18}/>, label: '我的偏好' },
];
export const SidebarNav: React.FC<SidebarNavProps> = ({ activeView, onChange, collapsed }) => {
    return (<div className={cn('flex flex-col gap-0.5 border-t border-stroke/60 py-2', RAIL_GUTTER)}>
      {navItems.map(({ view, icon, label }) => (<Tooltip key={view} content={label} position="right" disabled={!collapsed} className="w-full">
          <a href={`?view=${encodeURIComponent(view)}`} aria-current={activeView === view ? 'page' : undefined} onClick={(e) => {
                e.preventDefault();
                onChange(view);
            }} className={cn('touch-row relative flex h-10 w-full cursor-pointer items-center overflow-hidden rounded-card', 'transition-[background-color,color] duration-base ease-standard', RAIL_SLOT_INDENT, activeView === view
                ? 'bg-accent/10 font-medium text-accent'
                : 'text-ink-secondary hover:bg-ink/[0.05] hover:text-ink')}>
            <span className={RAIL_SLOT}>{icon}</span>

            <span className={cn(RAIL_LABEL, 'text-sm', collapsed ? 'opacity-0' : 'opacity-100')}>
              {label}
            </span>
          </a>
        </Tooltip>))}
    </div>);
};
