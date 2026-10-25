import { type TripPlannerConfiguration } from "../types/planner";
import { fetchJson } from "../../../lib/http";
export async function getTripPlannerConfiguration(): Promise<TripPlannerConfiguration> {
    return fetchJson<TripPlannerConfiguration>('/product/trip-planner');
}
