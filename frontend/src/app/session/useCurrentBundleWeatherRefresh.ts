import { refreshCurrentBundleWeather } from "../../features/travel/api/delivery";
import { useApp } from "../state/AppContext";
import { ApiError } from "../../lib/http";
import { apiErrorDetail } from "../../lib/apiErrorDetail";
import { conflictCurrentBundleId, readCurrentBundleAfterConflict } from "../../features/travel/model/bundleConflict";
import { isPublicDeliveryBundle } from "../../features/travel/types/delivery";
import React from 'react';
const MAX_REFRESH_ATTEMPTS = 3;
function retryableRefreshError(error: unknown): boolean {
    return !(error instanceof ApiError) || error.status === 429 || error.status >= 500;
}
function waitForRetry(ms: number): Promise<void> {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}
export function useCurrentBundleWeatherRefresh(enabled: boolean) {
    const { state, dispatch, currentStateRef } = useApp();
    const attemptedBundleIds = React.useRef(new Set<string>());
    const bundle = state.deliveryBundle;
    React.useEffect(() => {
        if (!enabled || !bundle || attemptedBundleIds.current.has(bundle.manifest.bundle_id))
            return;
        const { manifest } = bundle;
        attemptedBundleIds.current.add(manifest.bundle_id);
        const refreshId = `weather_${crypto.randomUUID()}`;
        let active = true;
        const request = {
            session_id: state.currentSessionId,
            refresh_id: refreshId,
            base_bundle_id: manifest.bundle_id,
            base_workspace_revision: manifest.workspace_revision,
            base_fact_data_revision: manifest.fact_data_revision,
            base_weather_data_revision: manifest.weather_data_revision,
        };
        const refresh = async () => {
            for (let attempt = 1; attempt <= MAX_REFRESH_ATTEMPTS && active; attempt += 1) {
                try {
                    const result = await refreshCurrentBundleWeather(manifest.run_id, request);
                    if (!active || !isPublicDeliveryBundle(result.bundle))
                        return;
                    attemptedBundleIds.current.add(result.bundle.manifest.bundle_id);
                    const current = currentStateRef.current.deliveryBundle;
                    if (!current || current.manifest.run_id !== manifest.run_id)
                        return;
                    if (result.bundle.manifest.bundle_id !== current.manifest.bundle_id) {
                        dispatch({ type: 'CONFIRM_DELIVERY_BUNDLE', payload: result.bundle });
                    }
                    return;
                }
                catch (error: unknown) {
                    if (!active)
                        return;
                    if (error instanceof ApiError && error.status === 409) {
                        if (apiErrorDetail(error).code === 'bundle_contract_superseded')
                            return;
                        if (conflictCurrentBundleId(error)) {
                            try {
                                const current = await readCurrentBundleAfterConflict(manifest.run_id, state.currentSessionId);
                                if (active)
                                    dispatch({ type: 'CONFIRM_DELIVERY_BUNDLE', payload: current });
                            }
                            catch {
                            }
                        }
                        return;
                    }
                    if (!retryableRefreshError(error) || attempt === MAX_REFRESH_ATTEMPTS)
                        return;
                    await waitForRetry(150 * 2 ** (attempt - 1));
                }
            }
        };
        void refresh();
        return () => {
            active = false;
        };
    }, [bundle, currentStateRef, dispatch, enabled, state.currentSessionId]);
}
