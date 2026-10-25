import { generatePresetInstructions, updatePreset, createPreset } from "../api/presets";
import { cn } from "../../../lib/utils";
import { describeRequestFailure } from "../../../lib/requestFailureMessage";
import { Button } from "../../../components/ui/Button";
import { Input } from "../../../components/ui/Input";
import { Modal } from "../../../components/ui/Modal";
import { SelectMenu, type SelectOption } from "../../../components/ui/SelectMenu";
import { PRESET_CATEGORY_LABELS, type TravelPreset, type PresetConstraints, type PresetCategory } from "../types/preset";
import { focusAreaChips, selectValuesIncludingStored } from "../model/openVocabularyOptions";
import { ChevronLeft, ChevronRight, Sparkles, Loader2, Save } from "lucide-react";
import { PRESET_ICON_CHOICES, getPresetIcon } from "./presetIcons";
import React, { useState, useCallback } from 'react';
const ICON_OPTIONS = PRESET_ICON_CHOICES;
const CATEGORY_OPTIONS = Object.entries(PRESET_CATEGORY_LABELS).map(([value, label]) => ({
    value,
    label,
}));
const toSelectOptions = (values: string[]): SelectOption[] => values.map((v) => ({ value: v, label: v || '不限' }));
const BUDGET_VALUES = ['', '经济', '中等', '奢华'];
const PACE_VALUES = ['', '紧凑', '悠闲', '弹性'];
const OUTPUT_STYLE_VALUES = ['', '详细日程表', '主题式推荐', '清单式', '故事式'];
const FOCUS_AREA_SUGGESTIONS = [
    '美食', '文化', '历史', '自然风光', '购物', '户外运动',
    '亲子活动', '摄影', '夜生活', '建筑', '非遗体验', '宗教',
    'SPA', '潜水', '徒步', '露营', '安全', '省钱攻略',
];
interface PresetCreatorProps {
    preset?: TravelPreset | null;
    onClose: () => void;
}
export const PresetCreator: React.FC<PresetCreatorProps> = ({ preset, onClose }) => {
    const isEdit = !!preset;
    const [step, setStep] = useState(0);
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState<string | null>(null);
    const [name, setName] = useState(preset?.name || '');
    const [description, setDescription] = useState(preset?.description || '');
    const [icon, setIcon] = useState(preset?.icon || 'compass');
    const [category, setCategory] = useState(preset?.category || 'custom');
    const [instructions, setInstructions] = useState(preset?.instructions || '');
    const [constraints, setConstraints] = useState<PresetConstraints>(preset?.constraints || {});
    const [aiPrompt, setAiPrompt] = useState('');
    const [aiLoading, setAiLoading] = useState(false);
    const [aiError, setAiError] = useState<string | null>(null);
    const [showAiChat, setShowAiChat] = useState(false);
    const [focusAreas, setFocusAreas] = useState<Set<string>>(new Set(preset?.constraints?.focus_areas || []));
    const steps = ['基本信息', '核心指令', '约束条件', '预览'];
    const canNext = () => {
        if (step === 0)
            return name.trim().length > 0;
        if (step === 1)
            return instructions.trim().length > 0;
        return true;
    };
    const handleAiGenerate = useCallback(async () => {
        if (!aiPrompt.trim() || aiLoading)
            return;
        setAiLoading(true);
        setAiError(null);
        try {
            const result = await generatePresetInstructions(aiPrompt);
            if (result.success && result.data) {
                const d = result.data;
                if (d.instructions)
                    setInstructions(d.instructions);
                if (d.name && !name)
                    setName(d.name);
                if (d.description && !description)
                    setDescription(d.description);
                if (d.icon && PRESET_ICON_CHOICES.some((opt) => opt.value === d.icon))
                    setIcon(d.icon);
                if (d.category && d.category in PRESET_CATEGORY_LABELS) {
                    setCategory(d.category as PresetCategory);
                }
                if (d.constraints) {
                    setConstraints(d.constraints);
                    if (d.constraints.focus_areas) {
                        setFocusAreas(new Set(d.constraints.focus_areas));
                    }
                }
                setShowAiChat(false);
                setAiPrompt('');
            }
            else {
                setAiError(result.error_message || 'AI 生成失败，请稍后再试或手动填写指令。');
            }
        }
        catch (e) {
            setAiError(describeRequestFailure(e, '读取', '生成结果').message);
        }
        finally {
            setAiLoading(false);
        }
    }, [aiPrompt, aiLoading, name, description]);
    const toggleFocusArea = (area: string) => {
        setFocusAreas((prev) => {
            const next = new Set(prev);
            if (next.has(area))
                next.delete(area);
            else
                next.add(area);
            return next;
        });
    };
    const handleSave = useCallback(async () => {
        if (saving)
            return;
        setSaving(true);
        setSaveError(null);
        try {
            const finalConstraints: PresetConstraints = {
                ...constraints,
                focus_areas: Array.from(focusAreas),
            };
            if (isEdit && preset) {
                await updatePreset(preset.id, {
                    name,
                    description,
                    icon,
                    category,
                    instructions,
                    constraints: finalConstraints,
                });
            }
            else {
                await createPreset({
                    name,
                    description,
                    icon,
                    category,
                    instructions,
                    constraints: finalConstraints,
                });
            }
            onClose();
        }
        catch (e) {
            setSaveError(describeRequestFailure(e, '保存', '这个旅行风格').message);
        }
        finally {
            setSaving(false);
        }
    }, [saving, isEdit, preset, name, description, icon, category, instructions, constraints, focusAreas, onClose]);
    return (<Modal open onClose={onClose} title={isEdit ? '编辑旅行风格' : '创建旅行风格'} maxWidth="max-w-2xl">
      <div className="-mx-6 -mb-6 flex max-h-[min(80vh,780px)] flex-col overflow-hidden">

        <div className="px-6 py-3 border-b border-stroke">
          <div className="flex items-center gap-2">
            {steps.map((s, i) => (<React.Fragment key={i}>
                <button onClick={() => i <= step && setStep(i)} className={cn('flex items-center gap-1.5 text-xs font-medium transition-colors', i === step ? 'text-accent' : i < step ? 'text-ink-secondary' : 'text-ink-muted')}>
                  <span className={cn('w-5 h-5 rounded-full flex items-center justify-center text-[11px] font-bold', i === step ? 'bg-accent text-white' : i < step ? 'bg-accent/20 text-accent' : 'bg-ink/10 text-ink-muted')}>
                    {i + 1}
                  </span>
                  {s}
                </button>
                {i < steps.length - 1 && (<div className={cn('flex-1 h-px', i < step ? 'bg-accent' : 'bg-stroke')}/>)}
              </React.Fragment>))}
          </div>
        </div>


        <div className="flex-1 overflow-y-auto overscroll-contain px-6 py-5 min-h-0">
          {step === 0 && (<div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-ink-secondary mb-1.5">名称</label>
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="如：日本温泉之旅" className="h-10"/>
              </div>
              <div>
                <label className="block text-xs font-medium text-ink-secondary mb-1.5">描述</label>
                <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="如：带孩子的慢节奏文化游" className="h-10"/>
              </div>
              <div>
                <label className="block text-xs font-medium text-ink-secondary mb-1.5">图标</label>
                <div className="flex flex-wrap gap-2">
                  {ICON_OPTIONS.map((opt) => (<button key={opt.value} type="button" onClick={() => setIcon(opt.value)} className={cn('w-10 h-10 rounded-card flex items-center justify-center transition-[color,background-color,transform] duration-base', icon === opt.value
                    ? 'bg-accent/10 text-accent border-2 border-accent/30'
                    : 'bg-ink/5 text-ink-secondary hover:bg-ink/10 border-2 border-transparent')} aria-label={opt.label} title={opt.label}>
                      <span className="flex items-center justify-center">
                        {getPresetIcon(opt.value, 18)}
                      </span>
                    </button>))}
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-ink-secondary mb-1.5">分类</label>
                <div className="flex flex-wrap gap-2">
                  {CATEGORY_OPTIONS.map((opt) => (<button key={opt.value} type="button" onClick={() => setCategory(opt.value as PresetCategory)} className={cn('px-3 py-1.5 rounded-card text-xs font-medium transition-colors duration-base', category === opt.value
                    ? 'bg-accent/10 text-accent border border-accent/20'
                    : 'bg-ink/5 text-ink-secondary border border-transparent hover:bg-ink/10')}>
                      {opt.label}
                    </button>))}
                </div>
              </div>
            </div>)}

          {step === 1 && (<div className="space-y-4">
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-xs font-medium text-ink-secondary">核心指令</label>
                  <button type="button" onClick={() => setShowAiChat(!showAiChat)} className={cn('flex items-center gap-1 px-2 py-1 rounded-card text-xs font-medium transition-colors duration-base', showAiChat
                ? 'bg-accent-soft text-accent'
                : 'bg-accent-soft/70 text-accent hover:bg-accent-soft')}>
                    <Sparkles size={12}/>
                    AI 辅助
                  </button>
                </div>
                <textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder={'你正在以「亲子慢游」模式为用户规划旅行。请遵循以下原则：\n1. 优先选择步行距离短、排队压力低、适合儿童休息的活动。\n2. 每天保留午休或机动时间，避免连续高强度移动。\n3. 对门票预约、年龄限制和安全注意事项给出可核验提醒。'} rows={12} className={cn('w-full rounded-card border border-stroke bg-surface px-3 py-2.5', 'text-sm text-ink placeholder:text-ink-muted leading-relaxed', 'resize-none transition-[color,background-color] duration-base')}/>
              </div>

              {showAiChat && (<div className="rounded-card border border-accent/15 bg-panel p-4 shadow-sm">
                  <div className="flex gap-2">
                    <textarea value={aiPrompt} onChange={(e) => setAiPrompt(e.target.value)} placeholder="例如：我想要一个帮我规划日本深度文化体验的风格，重点关注寺庙、茶道和传统手工艺" rows={3} className={cn('flex-1 rounded-card border border-accent/15 bg-surface px-3 py-2', 'text-sm text-ink placeholder:text-ink-muted leading-relaxed', 'resize-none')}/>
                  </div>
                  {aiError && (<p className="mt-2 text-xs leading-relaxed text-error">{aiError}</p>)}
                  <div className="flex justify-end mt-2">
                    <button type="button" onClick={handleAiGenerate} disabled={!aiPrompt.trim() || aiLoading} className={cn('flex items-center gap-1.5 px-3 py-1.5 rounded-card text-xs font-medium', 'transition-[color,background-color,opacity] duration-base ease-standard', aiPrompt.trim() && !aiLoading
                    ? 'bg-accent text-white hover:bg-accent-hover shadow-sm'
                    : 'bg-ink/5 text-ink-muted cursor-not-allowed')}>
                      {aiLoading ? <Loader2 size={12} className="animate-spin"/> : <Sparkles size={12}/>}
                      {aiLoading ? '生成中…' : '生成指令'}
                    </button>
                  </div>
                </div>)}
            </div>)}

          {step === 2 && (<div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-ink-secondary mb-1.5">时长建议</label>
                  <Input value={constraints.duration || ''} onChange={(e) => setConstraints({ ...constraints, duration: e.target.value || undefined })} placeholder="如 3-5天" className="h-9"/>
                </div>
                <div>
                  <label className="block text-xs font-medium text-ink-secondary mb-1.5">预算档位</label>
                  <SelectMenu testId="preset-budget" value={constraints.budget || ''} options={toSelectOptions(selectValuesIncludingStored(BUDGET_VALUES, constraints.budget))} onChange={(v) => setConstraints({ ...constraints, budget: v || undefined })} placeholder="不限" className="h-9"/>
                </div>
                <div>
                  <label className="block text-xs font-medium text-ink-secondary mb-1.5">行程节奏</label>
                  <SelectMenu testId="preset-pace" value={constraints.pace || ''} options={toSelectOptions(selectValuesIncludingStored(PACE_VALUES, constraints.pace))} onChange={(v) => setConstraints({ ...constraints, pace: v || undefined })} placeholder="不限" className="h-9"/>
                </div>
                <div>
                  <label className="block text-xs font-medium text-ink-secondary mb-1.5">输出风格</label>
                  <SelectMenu testId="preset-output-style" value={constraints.output_style || ''} options={toSelectOptions(selectValuesIncludingStored(OUTPUT_STYLE_VALUES, constraints.output_style))} onChange={(v) => setConstraints({ ...constraints, output_style: v || undefined })} placeholder="不限" className="h-9"/>
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-ink-secondary mb-1.5">关注领域</label>
                <div className="flex flex-wrap gap-1.5">
                  {focusAreaChips(FOCUS_AREA_SUGGESTIONS, Array.from(focusAreas)).map((area) => (<button key={area} type="button" onClick={() => toggleFocusArea(area)} className={cn('px-2.5 py-1 rounded-card text-xs font-medium transition-colors duration-base', focusAreas.has(area)
                    ? 'bg-accent/10 text-accent border border-accent/20'
                    : 'bg-ink/5 text-ink-secondary border border-transparent hover:bg-ink/10')}>
                      {area}
                    </button>))}
                </div>
              </div>
            </div>)}

          {step === 3 && (<div className="space-y-4">
              <div className="rounded-card border border-stroke bg-panel p-4 shadow-sm">
                <div className="flex items-center gap-2 mb-3">

                  <span className="flex items-center">{getPresetIcon(icon, 18)}</span>
                  <h3 className="text-sm font-bold text-ink">{name || '未命名旅行风格'}</h3>
                </div>
                {description && <p className="text-xs text-ink-secondary mb-3">{description}</p>}
                <div className="text-xs text-ink-secondary mb-2 font-medium">核心指令：</div>
                <pre className="text-xs text-ink leading-relaxed whitespace-pre-wrap bg-ink/[0.03] rounded-card p-3 max-h-[200px] overflow-y-auto">
                  {instructions || '无'}
                </pre>
                {focusAreas.size > 0 && (<div className="flex flex-wrap gap-1 mt-3">
                    {Array.from(focusAreas).map((area) => (<span key={area} className="text-[11px] px-1.5 py-0.5 rounded-label bg-accent/10 text-accent">
                        {area}
                      </span>))}
                  </div>)}
              </div>
            </div>)}
        </div>


        {saveError && (<div className="mx-6 mt-3 rounded-card border border-error/25 bg-error/[0.06] px-3 py-2">
            <p className="text-xs leading-relaxed text-error">{saveError}</p>
          </div>)}
        <div className="flex items-center justify-between px-6 py-4 border-t border-stroke">
          <div>
            {step > 0 && (<button onClick={() => setStep(step - 1)} className="flex items-center gap-1 text-xs text-ink-secondary hover:text-ink transition-colors">
                <ChevronLeft size={14}/>
                上一步
              </button>)}
          </div>
          <div className="flex items-center gap-2">
            {step < 3 ? (<Button variant="primary" size="sm" onClick={() => setStep(step + 1)} disabled={!canNext()} className="flex items-center gap-1">
                下一步
                <ChevronRight size={14}/>
              </Button>) : (<Button variant="primary" size="sm" onClick={handleSave} disabled={saving || !name.trim() || !instructions.trim()} className="flex items-center gap-1.5">
                {saving ? <Loader2 size={14} className="animate-spin"/> : <Save size={14}/>}
                {saving ? '保存中…' : isEdit ? '保存修改' : '创建旅行风格'}
              </Button>)}
          </div>
        </div>
      </div>
    </Modal>);
};
