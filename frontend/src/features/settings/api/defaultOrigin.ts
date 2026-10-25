import { type PlaceIdentity } from "../../travel/types/planner";
import { fetchJson } from "../../../lib/http";
export async function getDefaultOrigin(): Promise<PlaceIdentity | null> {
    const result = await fetchJson<{
        place: PlaceIdentity | null;
    }>('/user/default-origin');
    return result.place;
}
export async function setDefaultOrigin(place: PlaceIdentity): Promise<PlaceIdentity> {
    const result = await fetchJson<{
        place: PlaceIdentity;
    }>('/user/default-origin', {
        method: 'PUT', body: JSON.stringify({ place }),
    });
    return result.place;
}
