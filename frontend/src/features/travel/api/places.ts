import { type PlaceIdentity } from "../types/planner";
import { fetchJson, withQuery, SLOW_TIMEOUT_MS } from "../../../lib/http";
export async function searchPlaces(query: string, role: 'origin' | 'destination' | 'itinerary_place', options?: {
    signal?: AbortSignal;
}): Promise<{
    query: string;
    role: string;
    candidates: Array<{
        place: PlaceIdentity;
        confidence: number;
        requires_confirmation: boolean;
    }>;
}> {
    return fetchJson(withQuery('/places/search', { q: query, role }), { signal: options?.signal }, SLOW_TIMEOUT_MS);
}
