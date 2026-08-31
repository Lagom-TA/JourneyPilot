import { apiErrorDetail } from './apiErrorDetail';
import { describeRequestFailure, type RequestAction, type RequestFailure } from './requestFailureMessage';

/**
 * 每一种失败对旅行者说的那一句，**以及那一句之后他能按的那个键**。
 *
 * 句子由界面写（不许把后端原文印给旅行者，后端那份 `message`
 * 只进日志与别的客户端）。恢复动作和句子同源：
 *
 * - 文件本身的问题（格式不收、太大、打不开、超出解析上限）→ `none`。重发同一份文件、
 *   刷新页面都不会改变结果，**要换的是那份文件**；给一个按了没用的键比不给键更不诚实。
 * - 服务器现在忙不过来（`ingest_busy`）→ `retry`。这一种**换文件没用**，等一会儿
 *   同一份文件就能进去，和上面那几种正好相反。
 * - 寻址与归属的问题 → `reload`。这两种是界面自己的状态脏了，整页重来能拿到干净的。
 * - 这一篇不在了 → `reload`，重来一次拿到的是当前的列表。
 * - 正文没留存 → `none`，只能重新上传（**不给重试键**）。
 *
 * `no_indexable_text` 不在这张表里：它的句子取决于旅行者刚才给的是一份文件还是一段
 * 手输的字，由 `emptyTextMessage` 按动作说 —— 同一个 code 两种说法，不是两个 code。
 */
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
    message:
      '这篇资料是在「正文留存」之前加进来的，只剩切好的段落，看不到也改不了原文；重新上传一次就能编辑。',
    recovery: 'none',
  },
  unknown_source: {
    message: '这篇资料已经不在资料库里了。',
    recovery: 'reload',
  },
};

/**
 * 「这里面没有字」按输入的种类说话：一份文件要先转成文字，一段手输的字只要写点什么。
 * 同一道后端界（`_MIN_INDEXABLE_CHARS`），两种下一步动作。
 */
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

/**
 * 一次「把资料放进资料库」失败之后对旅行者说的那一句 —— 以及他能按的那个键。
 *
 * 为什么不能只用 `describeRequestFailure`：那一份按状态码回答，而这条路上有好几种
 * 4xx 的下一步动作与状态码给出的不一样 —— 一份没有文字的扫描版 PDF、一份损坏的
 * 文档、一份超过上限的文件，都不是「请求的信息不完整，请刷新页面后重试」。**请求是
 * 完整的**，刷新一百次也是同一个结果。
 *
 * 回落**留着**，而它守的是一件真事：FastAPI 自己的请求校验失败也是 422（`detail` 是
 * 一串 `{loc, msg}`、没有 code），那一种确实是「请求的信息不完整」，刷新页面拿到干净
 * 的界面状态是对的动作。所以回落不是兜底一个不认识的 code —— 后端能发的每一个 code
 * 这里都有一条自己的分支，回落只在两种已知形状之间收口。
 */
export function describeKnowledgeIngestFailure(
  error: unknown,
  action: Extract<RequestAction, '上传' | '添加'>,
): RequestFailure {
  return knownFailure(error, action) ?? describeRequestFailure(error, action, '资料库');
}

/**
 * 打开、保存或删除**某一篇**资料失败之后说的那一句。
 *
 * 和上面同一张表（同一批 code 出现在同一条产品路上），只有回落那一句的宾语不同：
 * 失败的是**一篇**，不是整库。
 */
export function describeKnowledgeSourceFailure(
  error: unknown,
  action: Extract<RequestAction, '读取' | '保存' | '删除'>,
): RequestFailure {
  return knownFailure(error, action) ?? describeRequestFailure(error, action, '这篇资料');
}
