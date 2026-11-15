import { describe, expect, it } from 'vitest';
import { isTripRunResumeAvailable, tripRunRecoveryFromDetail, type TripRunRecovery } from './runs';

const resumable: TripRunRecovery = {
  status: 'resume_available',
  reason: 'offline fixture',
  resumable: true,
};

describe('TripRun recovery helpers', () => {
  it('保留 execution 缺失时服务端授予的 resume 动作', () => {
    expect(tripRunRecoveryFromDetail({ execution: null, available_actions: ['resume'] })).toEqual({
      status: 'idle',
      reason: null,
      resumable: true,
    });
  });

  it.each(['failed', 'interrupted'] as const)('允许 %s Run 从检查点恢复', (status) => {
    expect(isTripRunResumeAvailable({
      status,
      recovery: resumable,
      readOnly: false,
      isStreaming: false,
    })).toBe(true);
  });

  it('不可恢复、只读或正在生成时不提供恢复资格', () => {
    expect(isTripRunResumeAvailable({
      status: 'failed',
      recovery: { ...resumable, resumable: false },
      readOnly: false,
      isStreaming: false,
    })).toBe(false);
    expect(isTripRunResumeAvailable({
      status: 'failed',
      recovery: resumable,
      readOnly: true,
      isStreaming: false,
    })).toBe(false);
    expect(isTripRunResumeAvailable({
      status: 'interrupted',
      recovery: resumable,
      readOnly: false,
      isStreaming: true,
    })).toBe(false);
  });

  it('不把取消或已完成 Run 当作可恢复', () => {
    expect(isTripRunResumeAvailable({ status: 'cancelled', recovery: resumable, readOnly: false, isStreaming: false })).toBe(false);
    expect(isTripRunResumeAvailable({ status: 'completed', recovery: resumable, readOnly: false, isStreaming: false })).toBe(false);
  });
});
