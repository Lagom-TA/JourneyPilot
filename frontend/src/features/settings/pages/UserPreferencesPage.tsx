import { usePreferenceResources } from "../hooks/usePreferenceResources";
import { updatePreferences } from "../api/profile";
import { addMemoryFact, deleteMemoryFact, deleteAllMemory, cleanupExpiredMemory } from "../api/memory";
import { AnimatePresence } from "motion/react";
import { Clock3, Eraser, Plus, Save, Trash2 } from "lucide-react";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { ConfirmAction } from "../../../components/ui/ConfirmAction";
import { Input } from "../../../components/ui/Input";
import { Modal } from "../../../components/ui/Modal";
import { PageShell, type SurfaceState } from "../../../components/ui/PageShell";
import { Chip } from "../../../components/ui/Chip";
import { RuledList, RuledRow } from "../../../components/ui/RuledList";
import { GROUP_LABEL, SECTION_NOTE, SECTION_TITLE } from "../../../lib/typography";
import { describeRequestFailure } from "../../../lib/requestFailureMessage";
import { buildPreferencePayload, preferenceChipGroups, togglePreferenceOption } from "../model/preferenceGroups";
import { ChartMark } from "../../../components/ui/ChartMark";
import { type MemoryFactItem } from "../types/memory";
import { type PreferenceOptionGroup } from "../types/profile";
import { PlaceField } from "../../travel/components/planning/TripPlanner";
import React, { useState } from 'react';
const memoryCategoryLabels: Record<string, string> = {
    preference: '偏好',
    constraint: '约束',
    trip_plan: '行程',
    feedback: '反馈',
};
function memoryCategoryLabel(category: string | null): string | null {
    if (!category)
        return null;
    return memoryCategoryLabels[category] || category;
}
const SECTION_RULE = 'border-t border-stroke/60 pt-10';
export const UserPreferencesPage: React.FC = () => {
    const [saving, setSaving] = useState(false);
    const [newMemory, setNewMemory] = useState('');
    const [adding, setAdding] = useState(false);
    const [busy, setBusy] = useState(false);
    const [showDeleteAllModal, setShowDeleteAllModal] = useState(false);
    const [statusMessage, setStatusMessage] = useState<string | null>(null);
    const [savingOrigin, setSavingOrigin] = useState(false);
    const { groups, selections, setSelections, facts, loading, factsUnavailable, defaultOrigin, setDefaultOrigin, loadError, loadAll, refreshFacts } = usePreferenceResources(setStatusMessage);
    const toggleOption = (group: PreferenceOptionGroup, option: string) => {
        setSelections((prev) => togglePreferenceOption(group, prev, option));
    };
    const handleSave = async () => {
        setSaving(true);
        setStatusMessage(null);
        try {
            await updatePreferences(buildPreferencePayload(groups, selections));
            setStatusMessage('偏好已保存。');
        }
        catch (err) {
            setStatusMessage(describeRequestFailure(err, '保存', '你的偏好').message);
        }
        finally {
            setSaving(false);
        }
    };
    const handleAddMemory = async () => {
        const content = newMemory.trim();
        if (!content || adding)
            return;
        setAdding(true);
        setStatusMessage(null);
        try {
            const result = await addMemoryFact(content);
            setNewMemory('');
            await refreshFacts();
            if (result.status === 'existing') {
                setStatusMessage('这条记忆本来就在列表里了，没有重复添加。');
            }
        }
        catch (err) {
            setStatusMessage(describeRequestFailure(err, '添加', '这条记忆').message);
        }
        finally {
            setAdding(false);
        }
    };
    const handleDeleteFact = async (fact: MemoryFactItem) => {
        setBusy(true);
        setStatusMessage(null);
        try {
            await deleteMemoryFact(fact.fact_id, {
                reason: `remove memory fact: ${fact.content}`,
            });
            await refreshFacts();
        }
        catch (err) {
            setStatusMessage(describeRequestFailure(err, '删除', '这条记忆').message);
        }
        finally {
            setBusy(false);
        }
    };
    const handleDeleteAll = async () => {
        setBusy(true);
        setStatusMessage(null);
        setShowDeleteAllModal(false);
        try {
            await deleteAllMemory({
                reason: 'user requested full first-party memory deletion',
                clear_auto_portrait: true,
                clear_graph: true,
                clear_session_anchors: true,
            });
            setStatusMessage('已删除。');
            await loadAll();
        }
        catch (err) {
            setStatusMessage(describeRequestFailure(err, '删除', '全部记忆').message);
        }
        finally {
            setBusy(false);
        }
    };
    const handleRetentionCleanup = async () => {
        setBusy(true);
        setStatusMessage(null);
        try {
            const cleanup = await cleanupExpiredMemory({
                reason: 'manual retention cleanup from Memory Center',
                limit: 1000,
            });
            setStatusMessage(cleanup.affected_facts > 0 ? `已清理 ${cleanup.affected_facts} 条过期记忆。` : '没有过期记忆。');
            await refreshFacts();
        }
        catch (err) {
            setStatusMessage(describeRequestFailure(err, '删除', '过期记忆').message);
        }
        finally {
            setBusy(false);
        }
    };
    const surfaceState: SurfaceState = loading
        ? { kind: 'loading' }
        : loadError
            ? {
                kind: 'error',
                title: '暂时读不到你的偏好',
                failure: loadError,
                onRetry: () => void loadAll(),
            }
            : { kind: 'ready' };
    return (<>
    <PageShell title="我的偏好" purpose="规划时会默认按这里的口味来" state={surfaceState}>
      <div className="flex flex-col gap-10">
        {statusMessage && (<p className="rounded-card border border-stroke bg-panel px-3.5 py-2.5 text-[13px] leading-relaxed text-ink-secondary">
            {statusMessage}
          </p>)}


        <section>
          <h2 className={SECTION_TITLE}>常用出发地</h2>
          <p className={SECTION_NOTE}>只影响之后新建的旅行。</p>

          <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-end">
            <PlaceField role="origin" value={defaultOrigin} onChange={setDefaultOrigin} label="出发地" frequent className="sm:max-w-sm"/>
            <Button variant="secondary" disabled={!defaultOrigin || savingOrigin} loading={savingOrigin} className="flex-shrink-0" onClick={async () => {
            if (!defaultOrigin)
                return;
            setSavingOrigin(true);
            try {
                await setDefaultOrigin(defaultOrigin);
                setStatusMessage('常用出发地已更新。');
            }
            catch (err) {
                setStatusMessage(describeRequestFailure(err, '保存', '常用出发地').message);
            }
            finally {
                setSavingOrigin(false);
            }
        }}>
              保存出发地
            </Button>
          </div>
        </section>


        <section className={SECTION_RULE}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className={SECTION_TITLE}>旅行偏好</h2>
              <p className={SECTION_NOTE}>选好这些常用偏好，规划时 JourneyPilot 会优先考虑。</p>
            </div>

            <Button variant="secondary" size="sm" onClick={handleSave} loading={saving} className="flex-shrink-0">
              <Save size={14}/>
              保存
            </Button>
          </div>


          <div className="mt-6 flex flex-col gap-7">
            {preferenceChipGroups(groups, selections).map((group, index) => (<div key={group.key} data-testid={`preference-group-${group.key}`}>
                <div className="flex items-baseline gap-2">
                  <h3 className={GROUP_LABEL}>{group.label}</h3>

                  {!group.multi && <span className="text-[11px] text-ink-muted">单选</span>}
                </div>
                <div className="mt-2.5 flex flex-wrap gap-2">
                  {group.chips.map(({ option, selected }) => (<Chip key={option} selected={selected} onClick={() => toggleOption(groups[index], option)}>
                      {option}
                    </Chip>))}
                </div>
              </div>))}
          </div>
        </section>


        <section className={SECTION_RULE}>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className={SECTION_TITLE}>个性记忆</h2>

              <p className={SECTION_NOTE}>
                这里的记忆会作为偏好带进每一次规划。与你本轮提出的要求冲突时，以本轮为准。
              </p>
            </div>
            <div className="flex flex-shrink-0 flex-wrap gap-2">
              <Button variant="ghost" size="sm" onClick={handleRetentionCleanup} disabled={busy || factsUnavailable}>
                <Clock3 size={14}/>
                清理过期
              </Button>

              <Button variant="ghost" size="sm" data-testid="memory-delete-all" onClick={() => setShowDeleteAllModal(true)} disabled={busy || factsUnavailable}>
                <Eraser size={14}/>
                删除全部
              </Button>
            </div>
          </div>


          <div className="mt-6 flex w-full items-end gap-3">
            <div className="min-w-0 flex-1">
              <Input value={newMemory} onChange={(e) => setNewMemory(e.target.value)} onKeyDown={(e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                void handleAddMemory();
            }
        }} placeholder="例如：我只坐直飞航班"/>
            </div>
            <Button variant="secondary" size="md" onClick={() => void handleAddMemory()} loading={adding} disabled={!newMemory.trim()} className="flex-shrink-0">
              <Plus size={14}/>
              添加
            </Button>
          </div>

          {facts.length === 0 ? (<div className="mt-6 flex flex-col items-center justify-center py-12 text-center">

              <ChartMark mark="blank-tabs" size={104} className="mb-5"/>
              <p className="text-base text-ink">还没有记忆</p>
              <p className="mt-1.5 text-xs text-ink-secondary">
                写一条你想让 JourneyPilot 记住的长期偏好，之后的规划会带上它。
              </p>
            </div>) : (<RuledList count={facts.length} topRule className="mt-4">
              <AnimatePresence initial={false}>
                {facts.map((fact) => {
                const catLabel = memoryCategoryLabel(fact.category);
                return (<RuledRow key={fact.fact_id} testId="memory-fact" title={<span className="font-medium">{fact.content}</span>} meta={<>
                          <Badge variant={fact.source === 'manual' ? 'accent' : 'default'}>
                            {fact.source === 'manual' ? '我添加的' : '自动提取'}
                          </Badge>
                          {catLabel && <Badge variant="default">{catLabel}</Badge>}
                        </>} trailing={<ConfirmAction onConfirm={() => void handleDeleteFact(fact)} confirmLabel="删除" disabled={busy}>
                          <Trash2 size={14}/>
                          删除
                        </ConfirmAction>}/>);
            })}
              </AnimatePresence>
            </RuledList>)}
        </section>
      </div>
    </PageShell>


    <Modal open={showDeleteAllModal} onClose={() => setShowDeleteAllModal(false)} title="删除全部记忆？">
      <div className="space-y-3">
        <p className="text-sm leading-relaxed text-ink-secondary">

          {facts.length > 0 ? `将删除下面这 ${facts.length} 条记忆，以及 ` : '下面还没有记忆，但仍会删除 '}
          JourneyPilot 自己从你的对话里总结出来的印象、印象之间的关联，还有各次对话的摘要。
        </p>
        <p className="text-sm leading-relaxed text-ink-secondary">
          你自己填的六组偏好与常用出发地不会动。
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setShowDeleteAllModal(false)}>
            取消
          </Button>
          <Button variant="primary" size="sm" data-testid="memory-delete-all-confirm" onClick={() => void handleDeleteAll()} loading={busy}>
            确认删除
          </Button>
        </div>
      </div>
    </Modal>
    </>);
};
