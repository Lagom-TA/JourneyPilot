import React, { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, Plus, Upload, X } from 'lucide-react';
import { useKnowledgeLibrary } from '../hooks/useKnowledgeLibrary';
import { Button } from '../../../components/ui/Button';
import { ConfirmAction } from '../../../components/ui/ConfirmAction';
import { TextArea } from '../../../components/ui/Input';
import { Modal } from '../../../components/ui/Modal';
import { PageShell, type SurfaceState } from '../../../components/ui/PageShell';
import { RequestFailureNotice } from '../../../components/ui/RequestFailureNotice';
import { PreferenceSectionNav } from '../../../app/components/PreferenceSectionNav';
import { useIsMobileViewport } from '../../../hooks/useMediaQuery';

function sourceTitle(source: string): string {
  if (!source.startsWith('manual-input-')) return source;
  const date = new Date(source.slice('manual-input-'.length));
  return Number.isNaN(date.getTime()) ? source : `文本资料 · ${date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })}`;
}
function sourceType(source: string): string {
  const extension = source.split('.').pop()?.toLowerCase();
  return ({ txt: 'TXT', md: 'Markdown', pdf: 'PDF', docx: 'Word' } as Record<string, string>)[extension ?? ''] ?? '文本';
}

export const KnowledgeBasePage: React.FC = () => {
  const [showAddModal, setShowAddModal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [manualContent, setManualContent] = useState('');
  const [editing, setEditing] = useState(false);
  const [pendingSource, setPendingSource] = useState<{ source: string | null } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sourceOpenerRef = useRef<HTMLButtonElement | null>(null);
  const documentHeadingRef = useRef<HTMLHeadingElement>(null);
  const mobile = useIsMobileViewport();
  const library = useKnowledgeLibrary(manualContent, setManualContent, setShowAddModal, setShowDeleteModal);
  const { uploadLimit, limitError, loadUploadLimit, manualError, setManualError, retryDocument, stats, loadingStats, loadError, isUploading, isIndexing, isDeleting, statusMessage, setStatusMessage, statusTone, openSource, setOpenSource, sourceDocument, draft, setDraft, loadingDocument, documentError, isSaving, isDeletingSource, loadStats, closeSource, handleSaveSource, handleDeleteSource, handleFileUpload, handleManualIndex, handleDeleteCollection } = library;
  const sources = stats?.source_details ?? [];
  const busy = isIndexing || isUploading || isDeleting;
  const documentBusy = isSaving || isDeletingSource;
  const dirty = openSource !== null && editing && draft !== sourceDocument?.content;
  useEffect(() => { if (mobile && openSource) documentHeadingRef.current?.focus(); }, [mobile, openSource]);

  const moveToSource = (source: string | null) => {
    setEditing(false);
    if (source) setOpenSource(source);
    else {
      closeSource();
      requestAnimationFrame(() => sourceOpenerRef.current?.focus());
    }
  };
  const selectSource = (source: string | null) => {
    if (documentBusy || source === openSource) return;
    if (dirty) setPendingSource({ source });
    else moveToSource(source);
  };
  const surfaceState: SurfaceState = loadingStats ? { kind: 'loading' } : loadError
    ? { kind: 'error', title: '暂时读不到资料库', failure: loadError, onRetry: () => void loadStats() } : { kind: 'ready' };
  const uploadNote = <div className="knowledge-upload-note">
    {limitError ? <RequestFailureNotice title="暂时读不到上传限制" failure={limitError} onRetry={() => void loadUploadLimit()} /> : <>TXT、Markdown、PDF、DOCX{uploadLimit ? ` · 单份不超过 ${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(uploadLimit / 1024 / 1024)} MB` : ' · 正在读取大小限制'}</>}
  </div>;

  return <>
    <PageShell title="资料来源" navigation={<PreferenceSectionNav />} state={surfaceState}
      readout={!loadingStats && !loadError && sources.length ? `${sources.length} 份资料` : undefined}
      actions={<>
        <Button variant="secondary" size="sm" onClick={() => { setManualError(null); setShowAddModal(true); }} disabled={busy}><Plus size={15} />添加文本</Button>
        <input ref={fileInputRef} type="file" aria-label="上传旅行资料" accept=".txt,.md,.pdf,.docx" className="sr-only" disabled={busy || !uploadLimit} onChange={handleFileUpload} />
        <Button size="sm" loading={isUploading} disabled={isIndexing || isDeleting || !uploadLimit} onClick={() => fileInputRef.current?.click()}><Upload size={15} />上传文件</Button>
      </>}>
      {statusMessage && <p role={statusTone === 'error' ? 'alert' : 'status'} className={`archive-status${statusTone === 'error' ? ' is-error' : ''}`}>{statusMessage}<button type="button" aria-label="关闭状态提示" className="ml-4 align-middle" onClick={() => setStatusMessage(null)}><X size={13} /></button></p>}
      {!sources.length ? <div className="archive-empty"><h2>把旅行资料放在这里</h2><p>攻略、住宿备选或交通笔记。</p>{uploadNote}</div> : <>
        <div className={`knowledge-workbench${openSource ? ' has-document' : ''}`}>
          <div className="knowledge-source-list" aria-label="资料列表">{sources.map(source => <button type="button" className="knowledge-source-button" data-testid={`knowledge-source-row-${source.source}`} key={source.source} aria-current={openSource === source.source ? 'true' : undefined} disabled={documentBusy} onClick={event => { sourceOpenerRef.current = event.currentTarget; selectSource(source.source); }}>
            <span>{sourceTitle(source.source)}</span><small>{sourceType(source.source)}</small><ArrowRight size={15} aria-hidden />
          </button>)}</div>
          {openSource && <section className="knowledge-document" aria-label="资料正文">
            <button type="button" className="archive-link knowledge-document-back" disabled={documentBusy} onClick={() => selectSource(null)}><ArrowLeft size={15} />返回资料</button>
            <header><h2 ref={documentHeadingRef} tabIndex={-1}>{sourceTitle(openSource)}</h2><Button variant="icon" size="sm" aria-label="关闭正文" disabled={documentBusy} onClick={() => selectSource(null)}><X size={17} /></Button></header>
            {loadingDocument ? <p role="status" className="archive-note">正在读取正文…</p> : documentError && !sourceDocument ? <RequestFailureNotice title="暂时读不到正文" failure={documentError} onRetry={retryDocument} /> : <>
              {editing ? <TextArea aria-label="资料正文" value={draft} disabled={documentBusy} onChange={event => setDraft(event.target.value)} rows={16} /> : <div className="knowledge-document-content">{sourceDocument?.content}</div>}
              {documentError && <p role="alert" className="mt-4 text-sm text-error">{documentError.message}</p>}
            </>}
            {!loadingDocument && <footer>
              <ConfirmAction testId="knowledge-source-delete" onConfirm={() => void handleDeleteSource()} confirmLabel="确认删除" confirmPending={isDeletingSource} disabled={isSaving} className="border-transparent bg-transparent px-0">删除这篇</ConfirmAction>
              {sourceDocument && <div>{editing ? <><Button variant="secondary" size="sm" disabled={documentBusy} onClick={() => { setEditing(false); setDraft(sourceDocument.content); }}>取消编辑</Button><Button size="sm" loading={isSaving} disabled={isDeletingSource || !draft.trim() || !dirty} onClick={() => void handleSaveSource()}>保存正文</Button></> : <Button variant="secondary" size="sm" disabled={documentBusy} onClick={() => setEditing(true)}>编辑正文</Button>}</div>}
            </footer>}
          </section>}
        </div>
        {uploadNote}
        <div className="knowledge-library-footer"><Button variant="ghost" size="sm" disabled={busy || documentBusy} onClick={() => { setStatusMessage(null); setShowDeleteModal(true); }}>清空资料库</Button></div>
      </>}
    </PageShell>
    <Modal open={showAddModal} onClose={() => { if (!isIndexing) setShowAddModal(false); }} title="添加旅行资料" maxWidth="max-w-2xl">
      <TextArea aria-label="旅行资料正文" placeholder="粘贴攻略、住宿备选或交通笔记" value={manualContent} onChange={event => setManualContent(event.target.value)} disabled={isIndexing} rows={10} />
      {manualError && <p role="alert" className="mt-4 text-sm text-error">{manualError}</p>}
      <div className="mt-6 flex justify-end gap-3"><Button variant="secondary" size="sm" disabled={isIndexing} onClick={() => setShowAddModal(false)}>取消</Button><Button size="sm" loading={isIndexing} disabled={!manualContent.trim() || isUploading || isDeleting} onClick={() => void handleManualIndex()}>添加资料</Button></div>
    </Modal>
    <Modal open={showDeleteModal} onClose={() => { if (!isDeleting) setShowDeleteModal(false); }} title="清空资料库？">
      <p className="text-sm text-ink-secondary">将删除全部 {sources.length} 份资料，无法撤销。</p>
      {statusTone === 'error' && statusMessage && <p role="alert" className="mt-4 text-sm text-error">{statusMessage}</p>}
      <div className="mt-6 flex justify-end gap-3"><Button variant="secondary" size="sm" disabled={isDeleting} onClick={() => setShowDeleteModal(false)}>取消</Button><Button size="sm" loading={isDeleting} onClick={() => void handleDeleteCollection()}>清空资料库</Button></div>
    </Modal>
    <Modal open={pendingSource !== null} onClose={() => setPendingSource(null)} title="放弃未保存的修改？">
      <div className="flex justify-end gap-3"><Button variant="secondary" size="sm" onClick={() => setPendingSource(null)}>继续编辑</Button><Button size="sm" onClick={() => { if (pendingSource) moveToSource(pendingSource.source); setPendingSource(null); }}>放弃修改</Button></div>
    </Modal>
  </>;
};
