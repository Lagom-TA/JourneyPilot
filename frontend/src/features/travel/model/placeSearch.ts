import { searchPlaces } from "../api/places";
import { type PlaceIdentity } from "../types/planner";
import { describeRequestFailure } from "../../../lib/requestFailureMessage";
export const PLACE_SEARCH_TIMEOUT_MS = 30000;
const EMPTY_RESULT_MESSAGE: Record<PlaceSearchRole, string> = {
    origin: '没有找到可用的城市、机场或火车站',
    destination: '请选择城市、行政区域、岛屿或景区型区域',
};
export type PlaceSearchRole = 'origin' | 'destination';
export interface PlaceSearchCandidate {
    place: PlaceIdentity;
    confidence: number;
}
export interface PlaceSearchSink {
    setLoading(value: boolean): void;
    setError(message: string): void;
    setCandidates(candidates: PlaceSearchCandidate[]): void;
}
type PlaceSearchFetcher = (query: string, role: PlaceSearchRole, options: {
    signal: AbortSignal;
}) => Promise<{
    candidates: PlaceSearchCandidate[];
}>;
export interface PlaceSearchRunner {
    run(query: string, sink: PlaceSearchSink): Promise<void>;
    cancel(): void;
}
function isAbort(reason: unknown): boolean {
    return (reason as {
        name?: string;
    } | null)?.name === 'AbortError';
}
export function createPlaceSearchRunner(role: PlaceSearchRole, fetcher: PlaceSearchFetcher = searchPlaces): PlaceSearchRunner {
    let latest = 0;
    let inflight: AbortController | null = null;
    let clock: ReturnType<typeof setTimeout> | null = null;
    function stopClock() {
        if (clock !== null) {
            clearTimeout(clock);
            clock = null;
        }
    }
    function cancel() {
        inflight?.abort();
        inflight = null;
        stopClock();
        latest += 1;
    }
    return {
        cancel,
        async run(query, sink) {
            inflight?.abort();
            stopClock();
            const ticket = ++latest;
            const isCurrent = () => ticket === latest;
            const controller = new AbortController();
            inflight = controller;
            let timedOut = false;
            clock = setTimeout(() => {
                timedOut = true;
                controller.abort();
            }, PLACE_SEARCH_TIMEOUT_MS);
            sink.setLoading(true);
            sink.setError('');
            try {
                const result = await fetcher(query, role, { signal: controller.signal });
                if (!isCurrent())
                    return;
                sink.setCandidates(result.candidates);
                if (!result.candidates.length)
                    sink.setError(EMPTY_RESULT_MESSAGE[role]);
            }
            catch (reason) {
                if (!isCurrent())
                    return;
                if (timedOut) {
                    sink.setError('地点搜索超时，请重试');
                    return;
                }
                if (isAbort(reason))
                    return;
                sink.setError(describeRequestFailure(reason, '读取', '地点候选').message);
            }
            finally {
                if (isCurrent()) {
                    stopClock();
                    inflight = null;
                    sink.setLoading(false);
                }
            }
        },
    };
}
