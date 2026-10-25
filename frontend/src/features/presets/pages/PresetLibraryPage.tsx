import { usePresetLibrary } from "../hooks/usePresetLibrary";
import { deletePreset } from "../api/presets";
import { m } from "motion/react";
import { Plus } from "lucide-react";
import { Chip } from "../../../components/ui/Chip";
import { useApp } from "../../../app/state/AppContext";
import { PresetCard } from "../components/PresetCard";
import { PresetCreator } from "../components/PresetCreator";
import { Button } from "../../../components/ui/Button";
import { PageShell, type SurfaceState } from "../../../components/ui/PageShell";
import { staggerContainer } from "../../../lib/motion";
import { type TravelPreset } from "../types/preset";
import React, { useState, useCallback } from 'react';
type FilterTab = 'all' | 'mine' | 'preset';
const FILTER_TABS: Array<{
    id: FilterTab;
    label: string;
}> = [
    { id: 'all', label: '全部' },
    { id: 'mine', label: '我的' },
    { id: 'preset', label: '官方' },
];
export const PresetLibraryPage: React.FC = () => {
    const { state, dispatch } = useApp();
    const [search, setSearch] = useState('');
    const [filter, setFilter] = useState<FilterTab>('all');
    const [showCreator, setShowCreator] = useState(false);
    const [editingPreset, setEditingPreset] = useState<TravelPreset | null>(null);
    const { presets, loading, loadError, loadPresets } = usePresetLibrary();
    const filteredPresets = presets.filter((p) => {
        if (search) {
            const q = search.toLowerCase();
            if (!p.name.toLowerCase().includes(q) && !p.description.toLowerCase().includes(q)) {
                return false;
            }
        }
        if (filter === 'mine')
            return !p.is_preset;
        if (filter === 'preset')
            return p.is_preset;
        return true;
    });
    const handleActivate = useCallback((preset: TravelPreset) => {
        if (state.activePresetId === preset.id) {
            dispatch({ type: 'SET_ACTIVE_PRESET', payload: null });
        }
        else {
            dispatch({
                type: 'SET_ACTIVE_PRESET',
                payload: { id: preset.id, name: preset.name },
            });
            dispatch({ type: 'SET_ACTIVE_VIEW', payload: 'chat' });
        }
    }, [state.activePresetId, dispatch]);
    const handleEdit = useCallback((preset: TravelPreset) => {
        setEditingPreset(preset);
        setShowCreator(true);
    }, []);
    const handleDelete = useCallback(async (preset: TravelPreset) => {
        try {
            await deletePreset(preset.id);
            if (state.activePresetId === preset.id) {
                dispatch({ type: 'SET_ACTIVE_PRESET', payload: null });
            }
            await loadPresets();
        }
        catch {
            await loadPresets();
        }
    }, [state.activePresetId, dispatch, loadPresets]);
    const handleCreatorClose = useCallback(() => {
        setShowCreator(false);
        setEditingPreset(null);
        void loadPresets();
    }, [loadPresets]);
    const surfaceState: SurfaceState = loading
        ? { kind: 'loading' }
        : loadError
            ? {
                kind: 'error',
                title: '暂时读不到旅行风格',
                failure: loadError,
                onRetry: () => void loadPresets(),
            }
            : presets.length === 0
                ? {
                    kind: 'empty',
                    mark: null,
                    line: '还没有旅行风格',
                    hint: '创建一个，规划时就能直接用。',
                }
                : filteredPresets.length === 0
                    ? {
                        kind: 'search-miss',
                        line: '没有找到匹配的旅行风格',
                        hint: search ? '试试其他关键词' : '这个分类下还没有风格',
                    }
                    : { kind: 'ready' };
    return (<>
      <PageShell title="旅行风格" purpose="选一个，规划时按它的口味安排" readout={presets.length > 0 ? `${presets.length} 个` : undefined} actions={<Button variant="primary" size="sm" onClick={() => {
                setEditingPreset(null);
                setShowCreator(true);
            }}>
            <Plus size={14}/>
            创建风格
          </Button>} search={{ value: search, onChange: setSearch, placeholder: '搜索旅行风格...' }} tabs={<div className="flex flex-wrap gap-2">
            {FILTER_TABS.map((tab) => (<Chip key={tab.id} selected={filter === tab.id} onClick={() => setFilter(tab.id)}>
                {tab.label}
              </Chip>))}
          </div>} state={surfaceState}>

        <m.div variants={staggerContainer(filteredPresets.length)} initial="hidden" animate="visible" className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {filteredPresets.map((preset) => (<PresetCard key={preset.id} preset={preset} isActive={state.activePresetId === preset.id} onActivate={handleActivate} onEdit={handleEdit} onDelete={handleDelete}/>))}
        </m.div>
      </PageShell>

      {showCreator && <PresetCreator preset={editingPreset} onClose={handleCreatorClose}/>}
    </>);
};
