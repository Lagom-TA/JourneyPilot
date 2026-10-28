import { useKnowledgeLibrary } from "../hooks/useKnowledgeLibrary";
import { Plus, Trash2, Upload } from "lucide-react";
import { Button } from "../../../components/ui/Button";
import { ConfirmAction } from "../../../components/ui/ConfirmAction";
import { TextArea } from "../../../components/ui/Input";
import { Modal } from "../../../components/ui/Modal";
import { PageShell, type SurfaceState } from "../../../components/ui/PageShell";
import { RuledList, RuledReadout, RuledRow } from "../../../components/ui/RuledList";
import { cn } from "../../../lib/utils";
import { type KnowledgeSourceDetail } from "../types/knowledge";
import React, { useRef, useState } from 'react';
export const KnowledgeBasePage: React.FC = () => {
    const [showAddModal, setShowAddModal] = useState(false);
    const [showDeleteModal, setShowDeleteModal] = useState(false);
    const [manualContent, setManualContent] = useState('');
    const fileInputRef = useRef<HTMLInputElement>(null);
    const { stats, loadingStats, loadError, isUploading, isIndexing, isDeleting, statusMessage, setStatusMessage, statusTone, openSource, setOpenSource, sourceDocument, draft, setDraft, loadingDocument, documentError, isSaving, isDeletingSource, loadStats, closeSource, handleSaveSource, handleDeleteSource, handleFileUpload, handleManualIndex, handleDeleteCollection } = useKnowledgeLibrary(manualContent, setManualContent, setShowAddModal, setShowDeleteModal);
    const chunkCount = stats?.total ?? 0;
    const sourceDetails: KnowledgeSourceDetail[] = stats?.source_details ?? [];
    const sourceCount = stats?.sources ?? 0;
    const busy = isIndexing || isUploading || isDeleting;
    const surfaceState: SurfaceState = loadingStats
        ? { kind: 'loading' }
        : loadError
            ? {
                kind: 'error',
                title: '暂时读不到资料库状态',
                failure: loadError,
                onRetry: () => void loadStats(),
            }
            : sourceDetails.length === 0
                ? {
                    kind: 'empty',
                    mark: 'empty-sleeve',
                    line: '还没有资料',
                    hint: '上传攻略、酒店备选或交通笔记，规划时会参考它们。',
                }
                : { kind: 'ready' };
    return (<>
      <PageShell title="资料来源" purpose="规划时会参考这里的资料" readout={!loadingStats && !loadError && chunkCount > 0
            ? `${chunkCount} 段 · ${sourceCount} 源`
            : undefined} actions={<>
            <Button variant="secondary" size="sm" onClick={() => setShowAddModal(true)} disabled={busy}>
              <Plus size={14}/>
              添加文本
            </Button>
            <input ref={fileInputRef} type="file" accept=".txt,.md,.pdf,.docx" className="sr-only" onChange={handleFileUpload} disabled={isUploading || isDeleting}/>
            <Button variant="primary" size="sm" loading={isUploading} disabled={isIndexing || isDeleting} type="button" onClick={() => fileInputRef.current?.click()}>
              <Upload size={14}/>
              上传文件
            </Button>
          </>} state={surfaceState}>
        <RuledList count={sourceDetails.length}>
          {sourceDetails.map((detail) => (<RuledRow key={detail.source} title={detail.source} onClick={() => setOpenSource(detail.source)} active={openSource === detail.source} testId={`knowledge-source-row-${detail.source}`} trailing={<RuledReadout>{detail.chunk_count} 段</RuledReadout>}/>))}
        </RuledList>


        <div className="mt-6 flex justify-end border-t border-stroke/60 pt-4">
          <Button variant="ghost" size="sm" onClick={() => setShowDeleteModal(true)} disabled={busy || (chunkCount === 0 && sourceCount === 0)}>
            <Trash2 size={14}/>
            删除资料库
          </Button>
        </div>
      </PageShell>


      {statusMessage && (<StatusLine tone={statusTone} onDismiss={() => setStatusMessage(null)}>
          {statusMessage}
        </StatusLine>)}

      <Modal open={showAddModal} onClose={() => setShowAddModal(false)} title="添加旅行资料" maxWidth="max-w-2xl">
        <TextArea placeholder="粘贴你的攻略、酒店备选、目的地笔记或交通说明..." value={manualContent} onChange={(e) => setManualContent(e.target.value)} rows={8} className="mb-4"/>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => setShowAddModal(false)}>
            取消
          </Button>
          <Button variant="primary" size="sm" onClick={handleManualIndex} loading={isIndexing} disabled={!manualContent.trim() || isUploading || isDeleting}>
            添加到资料库
          </Button>
        </div>
      </Modal>


      <Modal open={openSource !== null} onClose={closeSource} title={openSource ?? ''} maxWidth="max-w-3xl">
        {loadingDocument ? (<p className="py-6 text-center text-sm text-ink-secondary">正在读取正文…</p>) : documentError && !sourceDocument ? (<div className="space-y-4">
            <p className="text-sm leading-relaxed text-error">{documentError.message}</p>
            <div className="flex justify-between gap-2">
              <ConfirmAction onConfirm={() => void handleDeleteSource()} confirmPending={isDeletingSource} confirmLabel="删除" testId="knowledge-source-delete">
                <Trash2 size={14}/>
                删除这篇
              </ConfirmAction>
              <Button variant="secondary" size="sm" onClick={closeSource}>
                关闭
              </Button>
            </div>
          </div>) : (<div className="space-y-4">
            <TextArea value={draft} onChange={(e) => setDraft(e.target.value)} rows={16} aria-label="资料正文"/>

            <p className="text-xs leading-relaxed text-ink-secondary">
              当前 {sourceDocument?.chunk_count ?? 0} 段 · 保存会按新正文重新分段，规划时参考的就是保存后的这一份
            </p>
            {documentError && (<p className="text-sm leading-relaxed text-error">{documentError.message}</p>)}
            <div className="flex items-center justify-between gap-2">

              <ConfirmAction onConfirm={() => void handleDeleteSource()} confirmPending={isDeletingSource} confirmLabel="删除" disabled={isSaving} testId="knowledge-source-delete">
                <Trash2 size={14}/>
                删除这篇
              </ConfirmAction>
              <div className="flex gap-2">
                <Button variant="secondary" size="sm" onClick={closeSource} disabled={isSaving}>
                  取消
                </Button>
                <Button variant="primary" size="sm" onClick={() => void handleSaveSource()} loading={isSaving} disabled={isDeletingSource
                || !draft.trim()
                || draft === sourceDocument?.content}>
                  保存
                </Button>
              </div>
            </div>
          </div>)}
      </Modal>

      <Modal open={showDeleteModal} onClose={() => setShowDeleteModal(false)} title="删除资料库？">
        <div className="space-y-3">
          <p className="text-sm leading-relaxed text-ink-secondary">
            将删除 {chunkCount} 段资料，来自 {sourceCount} 个来源。
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setShowDeleteModal(false)}>
              取消
            </Button>
            <Button variant="primary" size="sm" onClick={handleDeleteCollection} loading={isDeleting} disabled={isUploading || isIndexing}>
              确认删除
            </Button>
          </div>
        </div>
      </Modal>
    </>);
};
const StatusLine: React.FC<{
    tone: 'ok' | 'error';
    onDismiss: () => void;
    children: React.ReactNode;
}> = ({ tone, onDismiss, children }) => (<div className="pointer-events-none fixed inset-x-0 bottom-4 z-30 flex justify-center px-6">
    <button type="button" onClick={onDismiss} className={cn('pointer-events-auto max-w-xl animate-slide-up rounded-card border bg-panel px-4 py-2.5', 'text-left text-xs leading-relaxed shadow-md', tone === 'error' ? 'border-error/30 text-error' : 'border-stroke text-ink-secondary')}>
      {children}
    </button>
  </div>);
