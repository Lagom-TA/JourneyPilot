import { type UserProfile, type PreferenceOptionGroup } from "../types/profile";
import { fetchJson } from "../../../lib/http";
export async function getUserProfile(): Promise<UserProfile> {
    return fetchJson<UserProfile>('/user/profile');
}
export async function getPreferenceOptions(): Promise<PreferenceOptionGroup[]> {
    return fetchJson<PreferenceOptionGroup[]>('/user/preference-options');
}
export async function updatePreferences(preferences: Record<string, unknown>): Promise<void> {
    await fetchJson<{
        status?: string;
    }>('/user/preferences', {
        method: 'PATCH',
        body: JSON.stringify({ preferences }),
    });
}
