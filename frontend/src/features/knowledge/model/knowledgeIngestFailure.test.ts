import { describe, expect, it } from "vitest";
import { ApiError } from "../../../lib/http";
import { describeKnowledgeIngestFailure } from "./knowledgeIngestFailure";
function apiError(status: number, code?: string): ApiError {
    return new ApiError('boom', status, code ? { detail: { code } } : { detail: 'plain' });
}
describe('knowledge ingest failure guidance', () => {
    it.each([
        ['collection_address_invalid', 400, 'reload'],
        ['unsupported_file_type', 422, 'none'],
        ['document_unreadable', 422, 'none'],
        ['ingest_busy', 503, 'retry'],
    ] as const)('%s maps to the appropriate recovery action', (code, status, recovery) => {
        const failure = describeKnowledgeIngestFailure(apiError(status, code), '上传');
        expect(failure.recovery).toBe(recovery);
    });
    it('does not offer retry for no-indexable-text inputs', () => {
        const upload = describeKnowledgeIngestFailure(apiError(422, 'no_indexable_text'), '上传');
        const typed = describeKnowledgeIngestFailure(apiError(422, 'no_indexable_text'), '添加');
        expect(upload).toMatchObject({ recovery: 'none' });
        expect(typed).toMatchObject({ recovery: 'none' });
    });
});
