export interface KnowledgeUploadResponse {
    chunks_indexed: number;
    collection: string;
    message: string;
}
export interface KnowledgeSourceDetail {
    source: string;
    chunk_count: number;
    updated_at?: string | null;
}
export interface KnowledgeCollectionStats {
    collection: string;
    total: number;
    sources: number;
    source_details: KnowledgeSourceDetail[];
    oldest: string | null;
    newest: string | null;
}
export interface KnowledgeSourceDocument {
    collection: string;
    source: string;
    content: string;
    chunk_count: number;
    updated_at?: string | null;
}
export interface KnowledgeDeleteResponse {
    collection: string;
    deleted_chunks: number;
    message: string;
}
