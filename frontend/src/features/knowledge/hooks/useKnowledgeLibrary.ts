import { getKnowledgeCollectionStats, getKnowledgeSource, updateKnowledgeSource, deleteKnowledgeSource, knowledgeUploadFile, knowledgeIndex, knowledgeDeleteCollection } from "../api/knowledge";
import { describeRequestFailure, type RequestFailure } from "../../../lib/requestFailureMessage";
import { describeKnowledgeIngestFailure, describeKnowledgeSourceFailure } from "../model/knowledgeIngestFailure";
import { type KnowledgeCollectionStats, type KnowledgeSourceDocument } from "../types/knowledge";
import React, { useCallback, useEffect, useRef, useState } from 'react';
const DEFAULT_COLLECTION = 'travel_knowledge';
export function useKnowledgeLibrary(manualContent: string, setManualContent: (content: string) => void, setShowAddModal: (open: boolean) => void, setShowDeleteModal: (open: boolean) => void) {
    const [stats, setStats] = useState<KnowledgeCollectionStats | null>(null);
    const [loadingStats, setLoadingStats] = useState(true);
    const [loadError, setLoadError] = useState<RequestFailure | null>(null);
    const [isUploading, setIsUploading] = useState(false);
    const [isIndexing, setIsIndexing] = useState(false);
    const [isDeleting, setIsDeleting] = useState(false);
    const [statusMessage, setStatusMessage] = useState<string | null>(null);
    const [statusTone, setStatusTone] = useState<'ok' | 'error'>('ok');
    const [openSource, setOpenSource] = useState<string | null>(null);
    const [sourceDocument, setSourceDocument] = useState<KnowledgeSourceDocument | null>(null);
    const [draft, setDraft] = useState('');
    const [loadingDocument, setLoadingDocument] = useState(false);
    const [documentError, setDocumentError] = useState<RequestFailure | null>(null);
    const [isSaving, setIsSaving] = useState(false);
    const [isDeletingSource, setIsDeletingSource] = useState(false);
    const statsRequestIdRef = useRef(0);
    const documentRequestIdRef = useRef(0);
    const loadStats = useCallback(async () => {
        const requestId = ++statsRequestIdRef.current;
        setLoadingStats(true);
        setLoadError(null);
        try {
            const nextStats = await getKnowledgeCollectionStats(DEFAULT_COLLECTION);
            if (requestId !== statsRequestIdRef.current)
                return;
            setStats(nextStats);
        }
        catch (error) {
            if (requestId !== statsRequestIdRef.current)
                return;
            setStats(null);
            setLoadError(describeRequestFailure(error, '读取', '资料库'));
        }
        finally {
            if (requestId === statsRequestIdRef.current)
                setLoadingStats(false);
        }
    }, []);
    useEffect(() => {
        void loadStats();
        return () => {
            statsRequestIdRef.current += 1;
        };
    }, [loadStats]);
    useEffect(() => {
        if (openSource === null)
            return;
        const requestId = ++documentRequestIdRef.current;
        setLoadingDocument(true);
        setDocumentError(null);
        setSourceDocument(null);
        void (async () => {
            try {
                const next = await getKnowledgeSource(DEFAULT_COLLECTION, openSource);
                if (requestId !== documentRequestIdRef.current)
                    return;
                setSourceDocument(next);
                setDraft(next.content);
            }
            catch (error) {
                if (requestId !== documentRequestIdRef.current)
                    return;
                setDocumentError(describeKnowledgeSourceFailure(error, '读取'));
            }
            finally {
                if (requestId === documentRequestIdRef.current)
                    setLoadingDocument(false);
            }
        })();
    }, [openSource]);
    const setStatus = (message: string, tone: 'ok' | 'error') => {
        setStatusTone(tone);
        setStatusMessage(message);
    };
    const closeSource = () => {
        documentRequestIdRef.current += 1;
        setOpenSource(null);
        setSourceDocument(null);
        setDocumentError(null);
        setDraft('');
        setLoadingDocument(false);
    };
    const handleSaveSource = async () => {
        if (!openSource || isSaving)
            return;
        setIsSaving(true);
        try {
            const result = await updateKnowledgeSource(DEFAULT_COLLECTION, openSource, draft);
            setStatus(`已保存「${openSource}」，重新整理成 ${result.chunks_indexed} 段资料。`, 'ok');
            closeSource();
            await loadStats();
        }
        catch (error) {
            setDocumentError(describeKnowledgeSourceFailure(error, '保存'));
        }
        finally {
            setIsSaving(false);
        }
    };
    const handleDeleteSource = async () => {
        if (!openSource || isDeletingSource)
            return;
        setIsDeletingSource(true);
        try {
            const result = await deleteKnowledgeSource(DEFAULT_COLLECTION, openSource);
            setStatus(`已删除「${openSource}」，原有 ${result.deleted_chunks} 段资料。`, 'ok');
            closeSource();
            await loadStats();
        }
        catch (error) {
            setDocumentError(describeKnowledgeSourceFailure(error, '删除'));
        }
        finally {
            setIsDeletingSource(false);
        }
    };
    const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file || isUploading)
            return;
        setIsUploading(true);
        try {
            const result = await knowledgeUploadFile(file, DEFAULT_COLLECTION);
            setStatus(`已把「${file.name}」加入资料库，整理成 ${result.chunks_indexed} 段资料。`, 'ok');
            await loadStats();
        }
        catch (error) {
            setStatus(describeKnowledgeIngestFailure(error, '上传').message, 'error');
        }
        finally {
            setIsUploading(false);
            e.target.value = '';
        }
    };
    const handleManualIndex = async () => {
        if (!manualContent.trim() || isIndexing)
            return;
        setIsIndexing(true);
        try {
            const result = await knowledgeIndex(manualContent, DEFAULT_COLLECTION);
            setManualContent('');
            setShowAddModal(false);
            setStatus(`已添加到资料库，整理成 ${result.chunks_indexed} 段资料。`, 'ok');
            await loadStats();
        }
        catch (error) {
            setStatus(describeKnowledgeIngestFailure(error, '添加').message, 'error');
        }
        finally {
            setIsIndexing(false);
        }
    };
    const handleDeleteCollection = async () => {
        if (isDeleting)
            return;
        setIsDeleting(true);
        try {
            await knowledgeDeleteCollection(DEFAULT_COLLECTION);
            setStats(null);
            setShowDeleteModal(false);
            setStatus('已清空资料库。', 'ok');
            await loadStats();
        }
        catch (error) {
            setStatus(describeRequestFailure(error, '删除', '资料库').message, 'error');
        }
        finally {
            setIsDeleting(false);
        }
    };
    return { stats, loadingStats, loadError, isUploading, isIndexing, isDeleting, statusMessage, setStatusMessage, statusTone, openSource, setOpenSource, sourceDocument, draft, setDraft, loadingDocument, documentError, isSaving, isDeletingSource, loadStats, closeSource, handleSaveSource, handleDeleteSource, handleFileUpload, handleManualIndex, handleDeleteCollection };
}
