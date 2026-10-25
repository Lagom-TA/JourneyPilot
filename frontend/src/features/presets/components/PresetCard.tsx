import { m } from "motion/react";
import { cn } from "../../../lib/utils";
import { staggerItem } from "../../../lib/motion";
import { READOUT_LABEL } from "../../../lib/typography";
import { type TravelPreset, type PresetCategory, PRESET_CATEGORY_LABELS } from "../types/preset";
import { getPresetIcon } from "./presetIcons";
import { ConfirmAction } from "../../../components/ui/ConfirmAction";
import { Zap, Play, Pencil, Trash2 } from "lucide-react";
import React from 'react';
interface PresetCardProps {
    preset: TravelPreset;
    isActive?: boolean;
    onActivate?: (preset: TravelPreset) => void;
    onEdit?: (preset: TravelPreset) => void;
    onDelete?: (preset: TravelPreset) => void;
}
export const PresetCard: React.FC<PresetCardProps> = ({ preset, isActive, onActivate, onEdit, onDelete, }) => {
    const icon = getPresetIcon(preset.icon, 18);
    const categoryLabel = PRESET_CATEGORY_LABELS[preset.category as PresetCategory] || preset.category;
    const focusAreas = preset.constraints.focus_areas ?? [];
    const kindReadout = [categoryLabel, preset.is_preset ? '官方' : null].filter(Boolean).join(' · ');
    return (<m.div variants={staggerItem} data-testid={`preset-card-${preset.id}`} data-preset-active={isActive ? 'on' : 'off'} className={cn('flex flex-col gap-2.5 rounded-card border bg-panel p-4 transition-colors duration-fast', isActive
            ? 'border-accent bg-accent/[0.05]'
            : 'border-stroke hover:border-accent/40 hover:bg-accent/[0.02]')}>
      <div className="flex items-start gap-2.5">

        <div className={cn('flex size-9 flex-shrink-0 items-center justify-center', isActive ? 'text-accent' : 'text-ink-secondary')}>
          {icon}
        </div>

        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold text-ink">{preset.name}</h3>
          <p data-testid={`preset-card-kind-${preset.id}`} className={cn('mt-0.5 text-ink-muted', READOUT_LABEL)}>
            {kindReadout}
          </p>
        </div>
      </div>

      <p className="break-words text-xs leading-relaxed text-ink-secondary">
        {preset.description}
      </p>


      {focusAreas.length > 0 && (<div data-testid={`preset-card-focus-${preset.id}`} className="flex flex-wrap gap-1">
          {focusAreas.map((area) => (<span key={area} className="rounded-label bg-ink/5 px-1.5 py-0.5 text-xs text-ink-secondary">
              {area}
            </span>))}
        </div>)}

      <div className="mt-auto flex items-center justify-between gap-2 border-t border-stroke/60 pt-2.5">
        <span className="text-xs text-ink-muted">
          {preset.usage_count > 0 ? `使用 ${preset.usage_count} 次` : '尚未使用'}
        </span>

        <div className="flex items-center gap-1">
          {!preset.is_preset && onEdit && (<button type="button" aria-label="编辑这个风格" onClick={(e) => { e.stopPropagation(); onEdit(preset); }} className="rounded-card p-1.5 text-ink-muted transition-colors duration-fast hover:bg-ink/5 hover:text-ink">
              <Pencil size={13}/>
            </button>)}
          {!preset.is_preset && onDelete && (<div onClick={(e) => e.stopPropagation()}>
              <ConfirmAction onConfirm={() => onDelete(preset)} confirmLabel="删除" triggerLabel="删除这个风格" className="border-transparent bg-transparent px-0 py-0">
                <Trash2 size={13}/>
              </ConfirmAction>
            </div>)}
          {onActivate && (<button onClick={(e) => { e.stopPropagation(); onActivate(preset); }} className={cn('flex items-center gap-1 rounded-label px-2 py-1 text-xs font-medium transition-colors duration-fast', isActive
                ? 'bg-accent text-white'
                : 'text-accent hover:bg-accent/10')}>
              {isActive ? (<>
                  <Zap size={11}/>
                  已激活
                </>) : (<>
                  <Play size={11}/>
                  激活
                </>)}
            </button>)}
        </div>
      </div>
    </m.div>);
};
