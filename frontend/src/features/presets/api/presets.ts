import { type TravelPreset, type PresetCreateData, type PresetUpdateData, type GenerateInstructionsResult } from "../types/preset";
import { fetchJson, LLM_TIMEOUT_MS } from "../../../lib/http";
export async function listPresets(): Promise<TravelPreset[]> {
    return fetchJson<TravelPreset[]>('/presets');
}
export async function createPreset(data: PresetCreateData): Promise<TravelPreset> {
    return fetchJson<TravelPreset>('/presets', {
        method: 'POST',
        body: JSON.stringify(data),
    });
}
export async function updatePreset(id: string, data: PresetUpdateData): Promise<TravelPreset> {
    return fetchJson<TravelPreset>(`/presets/${encodeURIComponent(id)}`, {
        method: 'PUT',
        body: JSON.stringify(data),
    });
}
export async function deletePreset(id: string): Promise<void> {
    await fetchJson<{
        status?: string;
    }>(`/presets/${encodeURIComponent(id)}`, {
        method: 'DELETE',
    });
}
export async function generatePresetInstructions(prompt: string): Promise<GenerateInstructionsResult> {
    return fetchJson<GenerateInstructionsResult>('/presets/generate-instructions', {
        method: 'POST',
        body: JSON.stringify({ description: prompt }),
    }, LLM_TIMEOUT_MS);
}
