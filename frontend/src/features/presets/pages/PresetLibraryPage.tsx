import { usePresetLibrary } from "../hooks/usePresetLibrary";
import { deletePreset } from "../api/presets";
import { Plus } from "lucide-react";
import { useApp } from "../../../app/state/AppContext";
import { PresetCard } from "../components/PresetCard";
import { PresetCreator } from "../components/PresetCreator";
import { Button } from "../../../components/ui/Button";
import { PageShell, type SurfaceState } from "../../../components/ui/PageShell";
import { PreferenceSectionNav } from "../../../app/components/PreferenceSectionNav";
import { useStartNewTrip } from "../../../app/session/useStartNewTrip";
import { describeRequestFailure } from "../../../lib/requestFailureMessage";
import { type TravelPreset } from "../types/preset";
import React, { useState, useCallback } from 'react';
type FilterTab = 'all' | 'mine' | 'preset';
const FILTER_TABS: Array<{
    id: FilterTab;
    label: string;
}> = [
    { id: 'all', label: '全部' },
    { id: 'mine', label: '我的' },
    { id: 'preset', label: '内置' },
];
export const PresetLibraryPage: React.FC = () => {
    const { state, dispatch } = useApp();
    const startNewTrip = useStartNewTrip();
    const [deletingId, setDeletingId] = useState<string | null>(null);
    const [deleteError, setDeleteError] = useState<{ id: string; message: string } | null>(null);
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
            startNewTrip();
        }
    }, [state.activePresetId, dispatch, startNewTrip]);
    const handleEdit = useCallback((preset: TravelPreset) => {
        setEditingPreset(preset);
        setShowCreator(true);
    }, []);
    const handleDelete = useCallback(async (preset: TravelPreset) => {
        if (deletingId) return;
        setDeletingId(preset.id);
        setDeleteError(null);
        try {
            await deletePreset(preset.id);
            if (state.activePresetId === preset.id) {
                dispatch({ type: 'SET_ACTIVE_PRESET', payload: null });
            }
            await loadPresets();
        }
        catch (err) {
            setDeleteError({ id: preset.id, message: describeRequestFailure(err, '删除', '这个旅行风格').message });
        }
        finally { setDeletingId(null); }
    }, [state.activePresetId, dispatch, loadPresets, deletingId]);
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
      <PageShell title="旅行风格" navigation={<PreferenceSectionNav />} readout={presets.length > 0 ? `${presets.length} 个` : undefined} actions={<Button variant="primary" size="sm" onClick={() => {
                setEditingPreset(null);
                setShowCreator(true);
            }}>
            <Plus size={14}/>
            创建风格
          </Button>} search={{ value: search, onChange: setSearch, placeholder: '搜索旅行风格' }} tabs={<>
            {FILTER_TABS.map((tab) => (<button type="button" key={tab.id} aria-pressed={filter === tab.id} onClick={() => setFilter(tab.id)}>
                {tab.label}
              </button>))}
          </>} state={surfaceState}>

        <div className="preset-library-grid">
          {filteredPresets.map((preset) => (<PresetCard key={preset.id} preset={preset} isActive={state.activePresetId === preset.id} onActivate={handleActivate} onEdit={handleEdit} onDelete={handleDelete} deleting={deletingId === preset.id} deleteError={deleteError?.id === preset.id ? deleteError.message : undefined}/>))}
        </div>
      </PageShell>

      {showCreator && <PresetCreator preset={editingPreset} onClose={handleCreatorClose}/>}
    </>);
};
