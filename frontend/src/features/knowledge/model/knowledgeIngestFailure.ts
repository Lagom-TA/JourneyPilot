import { apiErrorDetail } from "../../../lib/apiErrorDetail";
import { describeRequestFailure, type RequestAction, type RequestFailure } from "../../../lib/requestFailureMessage";
const FAILURE_BY_CODE: Record<string, RequestFailure> = {
    collection_address_invalid: {
        message: '这一屏指向的资料库地址不对，刷新页面后重来。',
        recovery: 'reload',
    },
    unsupported_file_type: {
        message: '这个格式读不了，换成纯文本、Markdown、PDF 或 Word 文档再上传。',
        recovery: 'none',
    },
    file_too_large: {
        message: '这份文件太大了，拆成几份或压缩后再上传。',
        recovery: 'none',
    },
    document_unreadable: {
        message: '这份文件打不开，可能已经损坏或者后缀名和真实格式不符；重新导出一份再上传。',
        recovery: 'none',
    },
    document_too_complex: {
        message: '这份文档太复杂了（页数太多或压缩包展开后太大），拆成几份再上传。',
        recovery: 'none',
    },
    document_parse_timeout: {
        message: '这份文档在限定时间内没能读完，换一份更简单的版本或拆开再上传。',
        recovery: 'none',
    },
    ingest_busy: {
        message: '正在处理的文档太多，稍等片刻再上传这一份。',
        recovery: 'retry',
    },
    document_text_unavailable: {
        message: '这篇资料是在「正文留存」之前加进来的，只剩切好的段落，看不到也改不了原文；重新上传一次就能编辑。',
        recovery: 'none',
    },
    unknown_source: {
        message: '这篇资料已经不在资料库里了。',
        recovery: 'reload',
    },
};
function emptyTextMessage(action: RequestAction): string {
    if (action === '上传') {
        return '这份文件里没有能读出来的文字，扫描版 PDF 需要先转成文字再上传。';
    }
    return `这段内容是空的，写点什么再${action}。`;
}
function knownFailure(error: unknown, action: RequestAction): RequestFailure | null {
    const { code } = apiErrorDetail(error);
    if (code === 'no_indexable_text') {
        return { message: emptyTextMessage(action), recovery: 'none' };
    }
    if (code && code in FAILURE_BY_CODE) {
        return FAILURE_BY_CODE[code];
    }
    return null;
}
export function describeKnowledgeIngestFailure(error: unknown, action: Extract<RequestAction, '上传' | '添加'>): RequestFailure {
    return knownFailure(error, action) ?? describeRequestFailure(error, action, '资料库');
}
export function describeKnowledgeSourceFailure(error: unknown, action: Extract<RequestAction, '读取' | '保存' | '删除'>): RequestFailure {
    return knownFailure(error, action) ?? describeRequestFailure(error, action, '这篇资料');
}
