import React from 'react';
import { ArrowRight, Pencil } from 'lucide-react';
import { ConfirmAction } from '../../../components/ui/ConfirmAction';
import { type TravelPreset, PRESET_CATEGORY_LABELS, type PresetCategory } from '../types/preset';

interface PresetCardProps {
  preset: TravelPreset;
  isActive?: boolean;
  deleting?: boolean;
  deleteError?: string;
  onActivate: (preset: TravelPreset) => void;
  onEdit: (preset: TravelPreset) => void;
  onDelete: (preset: TravelPreset) => void;
}

export const PresetCard: React.FC<PresetCardProps> = ({ preset, isActive, deleting, deleteError, onActivate, onEdit, onDelete }) => {
  const constraints = [
    ['时长', preset.constraints.duration], ['预算', preset.constraints.budget],
    ['节奏', preset.constraints.pace], ['呈现方式', preset.constraints.output_style],
    ['关注', preset.constraints.focus_areas?.join('、')],
  ].filter(([, value]) => value);
  return <article className="preset-entry" data-testid={`preset-card-${preset.id}`} data-preset-active={isActive ? 'on' : 'off'}>
    <header className="preset-entry-header"><h2>{preset.name}</h2>{(isActive || !preset.is_preset) && <small>{isActive ? '已选择' : '我的'}</small>}</header>
    {preset.description && <p>{preset.description}</p>}
    <details className="preset-entry-details"><summary>规划方式</summary>
      <p>{preset.instructions}</p>
      <dl><dt>分类</dt><dd data-testid={`preset-card-kind-${preset.id}`}>{PRESET_CATEGORY_LABELS[preset.category as PresetCategory] || preset.category} · {preset.is_preset ? '内置' : '我的'}</dd>
        {constraints.map(([label, value]) => <React.Fragment key={label}><dt>{label}</dt><dd>{value}</dd></React.Fragment>)}
      </dl>
    </details>
    {deleteError && <p role="alert" className="text-error">{deleteError}</p>}
    <footer><button type="button" className="archive-link" disabled={deleting} onClick={() => onActivate(preset)}>{isActive ? '取消选择' : '用于新旅行'}{!isActive && <ArrowRight size={15} />}</button>
      {!preset.is_preset && <div><button type="button" aria-label="编辑这个风格" disabled={deleting} className="archive-link" onClick={() => onEdit(preset)}><Pencil size={14} /></button><ConfirmAction onConfirm={() => onDelete(preset)} confirmLabel="确认删除" triggerLabel="删除这个风格" confirmPending={deleting} className="border-transparent bg-transparent px-0">删除</ConfirmAction></div>}
    </footer>
  </article>;
};
