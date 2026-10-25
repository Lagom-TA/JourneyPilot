import { type KnowledgeUploadResponse, type KnowledgeDeleteResponse, type KnowledgeSourceDocument, type KnowledgeCollectionStats } from "../types/knowledge";
import { fetchJson, DOCUMENT_TIMEOUT_MS, withQuery } from "../../../lib/http";
export async function knowledgeUploadFile(file: File, collection: string): Promise<KnowledgeUploadResponse> {
    const form = new FormData();
    form.append('file', file);
    form.append('collection', collection);
    form.append('source', file.name);
    return fetchJson<KnowledgeUploadResponse>('/knowledge/upload-file', {
        method: 'POST',
        body: form,
    }, DOCUMENT_TIMEOUT_MS);
}
export async function knowledgeIndex(content: string, collection: string, source = `manual-input-${new Date().toISOString()}`): Promise<KnowledgeUploadResponse> {
    return fetchJson<KnowledgeUploadResponse>('/knowledge/index', {
        method: 'POST',
        body: JSON.stringify({ content, collection, source }),
    }, DOCUMENT_TIMEOUT_MS);
}
export async function knowledgeDeleteCollection(collection: string): Promise<KnowledgeDeleteResponse> {
    return fetchJson<KnowledgeDeleteResponse>(`/knowledge/collection/${encodeURIComponent(collection)}`, {
        method: 'DELETE',
    });
}
export async function getKnowledgeSource(collection: string, source: string): Promise<KnowledgeSourceDocument> {
    return fetchJson<KnowledgeSourceDocument>(withQuery(`/knowledge/collections/${encodeURIComponent(collection)}/source`, {
        source,
    }));
}
export async function updateKnowledgeSource(collection: string, source: string, content: string): Promise<KnowledgeUploadResponse> {
    return fetchJson<KnowledgeUploadResponse>(withQuery(`/knowledge/collections/${encodeURIComponent(collection)}/source`, {
        source,
    }), {
        method: 'PUT',
        body: JSON.stringify({ content }),
    }, DOCUMENT_TIMEOUT_MS);
}
export async function deleteKnowledgeSource(collection: string, source: string): Promise<KnowledgeDeleteResponse> {
    return fetchJson<KnowledgeDeleteResponse>(withQuery(`/knowledge/collections/${encodeURIComponent(collection)}/source`, {
        source,
    }), {
        method: 'DELETE',
    });
}
export async function getKnowledgeCollectionStats(collection: string): Promise<KnowledgeCollectionStats> {
    return fetchJson<KnowledgeCollectionStats>(`/knowledge/collections/${encodeURIComponent(collection)}/stats`);
}
