import { ApiError } from './http';


export type RequestAction = '读取' | '上传' | '添加' | '删除' | '保存' | '重命名';

export type RequestRecovery = 'retry' | 'reload' | 'none';

export interface RequestFailure {
  message: string;
  recovery: RequestRecovery;
}

export function describeRequestFailure(
  error: unknown,
  action: RequestAction,
  subject: string,
): RequestFailure {
  if (error instanceof ApiError) {
    if (error.status === 403) {
      return { message: `当前用户无法${action}${subject}。`, recovery: 'none' };
    }
    if (error.status === 400 || error.status === 422) {
      return { message: `${action}请求的信息不完整，请刷新页面后重试。`, recovery: 'reload' };
    }
    if (error.status === 404 || error.status === 405) {
      return {
        message: `找不到${subject}的服务地址，请确认 JourneyPilot 正在运行，然后刷新页面。`,
        recovery: 'reload',
      };
    }
    if (error.status === 429) {
      return { message: `请求有点多，稍等片刻再${action}${subject}。`, recovery: 'retry' };
    }
    if (error.status >= 500) {
      return { message: `服务暂时无法${action}${subject}，请稍后重试。`, recovery: 'retry' };
    }
    // 收到未单独分类的 HTTP 响应不代表网络断开，重复请求未必能恢复。
    return {
      message: `服务端没有接受这次${action}，请刷新页面后再试。`,
      recovery: 'reload',
    };
  }
  return {
    message: `无法连接服务，${action}不到${subject}，请检查网络后重试。`,
    recovery: 'retry',
  };
}
