import { Search } from "lucide-react";
import { cn } from "../../../lib/utils";
import { Input } from "../../../components/ui/Input";
import { Tooltip } from "../../../components/ui/Tooltip";
import { RAIL_LABEL, RAIL_SLOT, RAIL_SLOT_INDENT } from "./rail";
import React from 'react';
interface SidebarSearchProps {
    value: string;
    onChange: (value: string) => void;
    collapsed?: boolean;
    onExpandAndFocus?: () => void;
    inputRef?: React.Ref<HTMLInputElement>;
}
export const SidebarSearch: React.FC<SidebarSearchProps> = ({ value, onChange, collapsed, onExpandAndFocus, inputRef, }) => {
    if (collapsed) {
        return (<Tooltip content="搜索对话" position="right" className="w-full">
        <button type="button" data-testid="sidebar-search-collapsed" onClick={onExpandAndFocus} className={cn('relative flex h-10 w-full items-center overflow-hidden rounded-card', 'text-ink-secondary transition-[background-color,color] duration-base ease-standard', 'hover:bg-ink/[0.05] hover:text-ink', RAIL_SLOT_INDENT)}>
          <span className={RAIL_SLOT}>
            <Search size={18}/>
          </span>
          <span className={cn(RAIL_LABEL, 'text-sm opacity-0')}>搜索对话</span>
        </button>
      </Tooltip>);
    }
    return (<Input ref={inputRef} name="conversation-search" data-testid="sidebar-search-input" autoComplete="off" icon={<Search size={18}/>} placeholder="搜索对话…" value={value} onChange={(event) => onChange(event.target.value)} iconClassName="left-[17px]" className="pl-[46px]"/>);
};
