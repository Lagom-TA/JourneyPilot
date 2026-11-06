import React, { useState } from 'react';
import { Clock3, Eraser, Plus } from 'lucide-react';
import { usePreferenceResources } from '../hooks/usePreferenceResources';
import { updatePreferences } from '../api/profile';
import { setDefaultOrigin as saveDefaultOrigin } from '../api/defaultOrigin';
import { addMemoryFact, deleteMemoryFact, deleteAllMemory, cleanupExpiredMemory } from '../api/memory';
import { Button } from '../../../components/ui/Button';
import { ConfirmAction } from '../../../components/ui/ConfirmAction';
import { Input } from '../../../components/ui/Input';
import { Modal } from '../../../components/ui/Modal';
import { PageShell, type SurfaceState } from '../../../components/ui/PageShell';
import { Chip } from '../../../components/ui/Chip';
import { RequestFailureNotice } from '../../../components/ui/RequestFailureNotice';
import { PreferenceSectionNav } from '../../../app/components/PreferenceSectionNav';
import { describeRequestFailure } from '../../../lib/requestFailureMessage';
import { buildPreferencePayload, preferenceChipGroups, togglePreferenceOption } from '../model/preferenceGroups';
import { type MemoryFactItem } from '../types/memory';
import { PlaceField } from '../../travel/components/planning/PlaceField';

type Feedback = { message: string; error?: boolean } | null;
function FeedbackLine({ value }: { value: Feedback }) {
  return value && <p className={`archive-status${value.error ? ' is-error' : ''}`} role={value.error ? 'alert' : 'status'}>{value.message}</p>;
}

export const UserPreferencesPage: React.FC = () => {
  const resources = usePreferenceResources();
  const { groups, selections, setSelections, facts, loading, defaultOrigin, setDefaultOrigin, loadError, loadAll, profileError, originError, factsError, refreshFacts, refreshOrigin, refreshProfile } = resources;
  const [saving, setSaving] = useState(false);
  const [savingOrigin, setSavingOrigin] = useState(false);
  const [newMemory, setNewMemory] = useState('');
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [deletingFactId, setDeletingFactId] = useState<string | null>(null);
  const [showDeleteAllModal, setShowDeleteAllModal] = useState(false);
  const [originFeedback, setOriginFeedback] = useState<Feedback>(null);
  const [preferenceFeedback, setPreferenceFeedback] = useState<Feedback>(null);
  const [memoryFeedback, setMemoryFeedback] = useState<Feedback>(null);
  const [deleteAllFeedback, setDeleteAllFeedback] = useState<Feedback>(null);

  const handleSaveOrigin = async () => {
    if (!defaultOrigin || savingOrigin) return;
    setSavingOrigin(true);
    setOriginFeedback(null);
    try {
      await saveDefaultOrigin(defaultOrigin);
      setOriginFeedback({ message: '常用出发地已保存。' });
    } catch (err) { setOriginFeedback({ message: describeRequestFailure(err, '保存', '常用出发地').message, error: true }); }
    finally { setSavingOrigin(false); }
  };
  const handleSave = async () => {
    if (saving || profileError) return;
    setSaving(true);
    setPreferenceFeedback(null);
    try {
      await updatePreferences(buildPreferencePayload(groups, selections));
      setPreferenceFeedback({ message: '旅行偏好已保存。' });
    } catch (err) { setPreferenceFeedback({ message: describeRequestFailure(err, '保存', '旅行偏好').message, error: true }); }
    finally { setSaving(false); }
  };
  const handleAddMemory = async () => {
    if (!newMemory.trim() || adding || busy || factsError) return;
    setAdding(true);
    setMemoryFeedback(null);
    try {
      const result = await addMemoryFact(newMemory.trim());
      setNewMemory('');
      setMemoryFeedback({ message: result.status === 'existing' ? '这条记忆已在列表中。' : '旅行记忆已添加。' });
      await refreshFacts();
    } catch (err) { setMemoryFeedback({ message: describeRequestFailure(err, '添加', '旅行记忆').message, error: true }); }
    finally { setAdding(false); }
  };
  const handleDeleteFact = async (fact: MemoryFactItem) => {
    if (busy || adding) return;
    setBusy(true);
    setDeletingFactId(fact.fact_id);
    setMemoryFeedback(null);
    try {
      await deleteMemoryFact(fact.fact_id, { reason: `remove memory fact: ${fact.content}` });
      setMemoryFeedback({ message: '已从记忆列表删除，偏好总结将在后续对话中同步更新。' });
      await refreshFacts();
    } catch (err) { setMemoryFeedback({ message: describeRequestFailure(err, '删除', '这条记忆').message, error: true }); }
    finally { setBusy(false); setDeletingFactId(null); }
  };
  const handleDeleteAll = async () => {
    if (busy) return;
    setBusy(true);
    setDeleteAllFeedback(null);
    try {
      await deleteAllMemory({ reason: 'user requested full first-party memory deletion', clear_auto_portrait: true, clear_graph: true, clear_session_anchors: true });
      setShowDeleteAllModal(false);
      setMemoryFeedback({ message: '旅行记忆已全部清空，手填偏好和常用出发地已保留。' });
      await refreshFacts();
    } catch (err) { setDeleteAllFeedback({ message: describeRequestFailure(err, '删除', '全部记忆').message, error: true }); }
    finally { setBusy(false); }
  };
  const handleRetentionCleanup = async () => {
    if (busy || adding) return;
    setBusy(true);
    setMemoryFeedback(null);
    try {
      const result = await cleanupExpiredMemory({ reason: 'manual retention cleanup from Memory Center', limit: 1000 });
      setMemoryFeedback({ message: result.affected_facts ? `已清理 ${result.affected_facts} 条过期记忆。` : '没有过期记忆。' });
      await refreshFacts();
    } catch (err) { setMemoryFeedback({ message: describeRequestFailure(err, '删除', '过期记忆').message, error: true }); }
    finally { setBusy(false); }
  };
  const surfaceState: SurfaceState = loading ? { kind: 'loading' } : loadError
    ? { kind: 'error', title: '暂时读不到偏好选项', failure: loadError, onRetry: () => void loadAll() } : { kind: 'ready' };

  return <>
    <PageShell title="我的偏好" navigation={<PreferenceSectionNav />} state={surfaceState}>
      <section className="preference-section">
        <h2>常用出发地</h2>
        <p className="archive-note">用于之后新建的旅行。</p>
        {originError ? <RequestFailureNotice title="暂时读不到常用出发地" failure={originError} onRetry={() => void refreshOrigin()} /> : <div className="preference-origin">
          <PlaceField role="origin" value={defaultOrigin} onChange={setDefaultOrigin} label="出发地" frequent />
          <Button variant="ghost" onClick={() => void handleSaveOrigin()} loading={savingOrigin} disabled={!defaultOrigin}>保存出发地</Button>
        </div>}
        <FeedbackLine value={originFeedback} />
      </section>
      <section className="preference-section">
        <div className="preference-section-header"><h2>旅行偏好</h2><Button variant="ghost" onClick={() => void handleSave()} loading={saving} disabled={!!profileError}>保存偏好</Button></div>
        <FeedbackLine value={preferenceFeedback} />
        {profileError ? <RequestFailureNotice title="暂时读不到旅行偏好" failure={profileError} onRetry={() => void refreshProfile()} /> : <div className="preference-fields">
          {preferenceChipGroups(groups, selections).map(group => <div className="preference-field" key={group.key} data-testid={`preference-group-${group.key}`}>
            <h3>{group.label === '旅行风格' ? '旅行兴趣' : group.label}</h3>
            <div className="preference-chips">{group.chips.map(({ option, selected }) => <Chip key={option} selected={selected} disabled={saving} onClick={() => setSelections(current => togglePreferenceOption(groups.find(item => item.key === group.key)!, current, option))}>{option}</Chip>)}</div>
          </div>)}
        </div>}
      </section>
      <section className="preference-section">
        <div className="preference-section-header"><h2>旅行记忆</h2></div>
        <FeedbackLine value={memoryFeedback} />
        {factsError ? <RequestFailureNotice title="暂时读不到旅行记忆" failure={factsError} onRetry={() => void refreshFacts()} /> : <>
          <div className="memory-input"><Input aria-label="新的记忆内容" placeholder="添加一条长期偏好" value={newMemory} disabled={busy || adding} onChange={event => setNewMemory(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); void handleAddMemory(); } }} /><Button variant="ghost" disabled={!newMemory.trim() || busy} loading={adding} onClick={() => void handleAddMemory()}><Plus size={15} />添加</Button></div>
          {facts.length ? facts.map(fact => <div className="memory-row" key={fact.fact_id} data-testid="memory-fact">
            <div><p>{fact.content}</p><small>{fact.source === 'manual' ? '我添加的' : '来自对话'}</small></div>
            <ConfirmAction onConfirm={() => void handleDeleteFact(fact)} confirmLabel="确认删除" confirmPending={deletingFactId === fact.fact_id} disabled={busy || adding} className="border-transparent bg-transparent px-0" triggerClassName="text-ink-secondary">删除</ConfirmAction>
          </div>) : <p className="archive-note">还没有旅行记忆。</p>}
        </>}
        <details className="preference-detail"><summary>记忆如何使用与管理</summary><p>记忆会用于后续规划；与本次要求冲突时，以本次为准。手动添加或单条删除后，系统会同步更新你的偏好总结；更新完成前，规划仍可能参考此前总结的内容。</p>
          <div className="memory-tools"><Button variant="ghost" size="sm" disabled={busy || adding || !!factsError} onClick={() => void handleRetentionCleanup()}><Clock3 size={14} />清理过期</Button><Button variant="ghost" size="sm" data-testid="memory-delete-all" disabled={busy || adding || !!factsError} onClick={() => { setDeleteAllFeedback(null); setShowDeleteAllModal(true); }}><Eraser size={14} />删除全部记忆</Button></div>
        </details>
      </section>
    </PageShell>
    <Modal open={showDeleteAllModal} onClose={() => { if (!busy) setShowDeleteAllModal(false); }} title="删除全部记忆？">
      <p className="text-sm leading-relaxed text-ink-secondary">将清除 {facts.length} 条记忆、对话偏好总结及手动管理内容。正在整理的记忆也会一并取消。</p>
      <p className="mt-3 text-sm leading-relaxed text-ink">手填偏好和常用出发地保留。</p>
      <FeedbackLine value={deleteAllFeedback} />
      <div className="mt-6 flex justify-end gap-3"><Button variant="secondary" size="sm" disabled={busy} onClick={() => setShowDeleteAllModal(false)}>取消</Button><Button size="sm" data-testid="memory-delete-all-confirm" loading={busy} onClick={() => void handleDeleteAll()}>删除全部记忆</Button></div>
    </Modal>
  </>;
};
