import { type PublicDeliveryBundle } from "../types/delivery";
import { fetchJson, withQuery, fetchBlob, DOCUMENT_TIMEOUT_MS, LLM_TIMEOUT_MS } from "../../../lib/http";
import { type WeatherBundleRefreshRequest, type WeatherBundleRefreshResponse } from "../types/weather";
export async function getCurrentDeliveryBundle(runId: string, sessionId?: string | null): Promise<PublicDeliveryBundle> {
    return fetchJson<PublicDeliveryBundle>(withQuery(`/trip-runs/${encodeURIComponent(runId)}/bundle/current`, {
        session_id: sessionId,
    }));
}
export async function exportCurrentTripReportPdf(bundle: PublicDeliveryBundle, sessionId?: string | null): Promise<{
    blob: Blob;
    filename: string;
    bundleId: string;
}> {
    const manifest = bundle.manifest;
    const result = await fetchBlob(`/trip-runs/${encodeURIComponent(manifest.run_id)}/bundle/current/pdf`, {
        method: 'POST',
        body: JSON.stringify({
            session_id: sessionId,
            bundle_id: manifest.bundle_id,
            workspace_revision: manifest.workspace_revision,
            fact_data_revision: manifest.fact_data_revision,
            weather_data_revision: manifest.weather_data_revision,
        }),
    }, DOCUMENT_TIMEOUT_MS);
    const disposition = result.headers.get('content-disposition') ?? '';
    return {
        blob: result.blob,
        filename: disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? 'journeypilot-trip.pdf',
        bundleId: result.headers.get('x-journeypilot-bundle-id') ?? '',
    };
}
export async function refreshCurrentBundleWeather(runId: string, request: WeatherBundleRefreshRequest): Promise<WeatherBundleRefreshResponse> {
    return fetchJson<WeatherBundleRefreshResponse>(`/trip-runs/${encodeURIComponent(runId)}/bundle/current/weather/refresh`, { method: 'POST', body: JSON.stringify(request) }, LLM_TIMEOUT_MS);
}
