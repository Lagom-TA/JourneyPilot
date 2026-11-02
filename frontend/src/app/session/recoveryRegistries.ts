export interface RecoveryRegistries {
  cursorByRun: Map<string, number>;
  readyRuns: Set<string>;
  finalizedRuns: Set<string>;
}

/**
 * 恢复通道只服务当前 Run；历史 Run 的游标与本轮集合不保留，避免长时间使用后无限增长。
 * 保留当前 Run 与最近 maxEntries-1 个，其余从三个集合中删除。
 */
export function pruneRecoveryRegistries(
  registries: RecoveryRegistries,
  currentRunId: string | null,
  maxEntries = 8,
): void {
  const ordered = [...registries.cursorByRun.keys()];
  if (currentRunId && !ordered.includes(currentRunId)) ordered.push(currentRunId);
  const keep = new Set<string>();
  if (currentRunId) keep.add(currentRunId);
  const remaining = ordered.filter((runId) => runId !== currentRunId);
  for (const runId of remaining.slice(-Math.max(0, maxEntries - keep.size))) keep.add(runId);
  for (const runId of ordered) {
    if (keep.has(runId)) continue;
    registries.cursorByRun.delete(runId);
    registries.readyRuns.delete(runId);
    registries.finalizedRuns.delete(runId);
  }
  for (const runId of [...registries.readyRuns]) {
    if (!keep.has(runId)) registries.readyRuns.delete(runId);
  }
  for (const runId of [...registries.finalizedRuns]) {
    if (!keep.has(runId)) registries.finalizedRuns.delete(runId);
  }
}
