import { describe, expect, it } from 'vitest';

import { ApiError } from './api';
import {
  describeKnowledgeIngestFailure,
  describeKnowledgeSourceFailure,
} from './knowledgeIngestFailure';

function apiError(status: number, code?: string): ApiError {
  return new ApiError('boom', status, code ? { detail: { code } } : { detail: 'plain' });
}

describe('knowledge ingest failure guidance', () => {
  it.each([
    ['collection_address_invalid', 400, 'reload', '地址'],
    ['unsupported_file_type', 422, 'none', '格式'],
    ['document_unreadable', 422, 'none', '打不开'],
    ['ingest_busy', 503, 'retry', '文档太多'],
  ] as const)('%s 给出对应的用户动作', (code, status, recovery, phrase) => {
    const failure = describeKnowledgeIngestFailure(apiError(status, code), '上传');

    expect(failure.recovery).toBe(recovery);
    expect(failure.message).toContain(phrase);
  });

  it('按输入种类解释 no_indexable_text，并避免误导性的重试键', () => {
    const upload = describeKnowledgeIngestFailure(apiError(422, 'no_indexable_text'), '上传');
    const typed = describeKnowledgeIngestFailure(apiError(422, 'no_indexable_text'), '添加');

    expect(upload).toMatchObject({ recovery: 'none' });
    expect(upload.message).toContain('扫描版');
    expect(typed).toMatchObject({ recovery: 'none' });
    expect(typed.message).toContain('写点什么');
    expect(upload.message).not.toBe(typed.message);
  });

  it('未知错误回落到对应的资料对象，而不是把单篇失败说成整库失败', () => {
    const failure = describeKnowledgeSourceFailure(apiError(500), '读取');

    expect(failure.message).toContain('这篇资料');
  });
});
