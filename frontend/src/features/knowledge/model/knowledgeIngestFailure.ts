import { apiErrorDetail } from "../../../lib/apiErrorDetail";
import { describeRequestFailure, type RequestAction, type RequestFailure } from "../../../lib/requestFailureMessage";
const FAILURE_BY_CODE: Record<string, RequestFailure> = {
    collection_address_invalid: {
        message: '当前资料库地址无效，请刷新页面后重试。',
        recovery: 'reload',
    },
    unsupported_file_type: {
        message: '这个格式暂不支持，请选择 TXT、Markdown、PDF 或 DOCX 文件再上传。',
        recovery: 'none',
    },
    file_too_large: {
        message: '这份文件超过大小限制，请拆成几份或压缩后再上传。',
        recovery: 'none',
    },
    document_unreadable: {
        message: '这份文件打不开，可能已经损坏或者后缀名和真实格式不符；重新导出一份再上传。',
        recovery: 'none',
    },
    document_too_complex: {
        message: '这份文档内容过多（页数或篇幅超出上限），请拆成几份再上传。',
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
        message: '这篇资料未保存完整原文，暂时无法查看或编辑；重新上传一次即可编辑。',
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
