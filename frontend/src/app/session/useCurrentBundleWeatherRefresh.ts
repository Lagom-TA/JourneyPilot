import { refreshCurrentBundleWeather } from "../../features/travel/api/delivery";
import { useApp } from "../state/AppContext";
import { ApiError } from "../../lib/http";
import { conflictCurrentBundleId, readCurrentBundleAfterConflict } from "../../features/travel/model/bundleConflict";
import { isPublicDeliveryBundle } from "../../features/travel/types/delivery";
import { randomId } from "../../lib/platform";
import React from 'react';
import { MAX_REFRESH_ATTEMPTS, shouldRetryWeatherRefresh, shouldStartWeatherRefresh, weatherRetryDelayMs } from "./weatherRefreshPolicy";
function waitForRetry(ms: number): Promise<void> {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}
export function useCurrentBundleWeatherRefresh(enabled: boolean) {
    const { state, dispatch, currentStateRef } = useApp();
    // 只有成功处理过的 base bundle 才记录；失败后允许 effect 重新触发时重试。
    const attemptedBundleIds = React.useRef(new Set<string>());
    const inFlightBundleIds = React.useRef(new Set<string>());
    const bundle = state.deliveryBundle;
    React.useEffect(() => {
        const bundleId = bundle?.manifest.bundle_id ?? null;
        if (!bundle || !shouldStartWeatherRefresh({
            enabled,
            bundleId,
            attempted: attemptedBundleIds.current,
            inFlight: inFlightBundleIds.current,
        }))
            return;
        const { manifest } = bundle;
        inFlightBundleIds.current.add(manifest.bundle_id);
        const refreshId = `weather_${randomId()}`;
        let active = true;
        const request = {
            session_id: state.currentSessionId,
            refresh_id: refreshId,
            base_bundle_id: manifest.bundle_id,
            base_workspace_revision: manifest.workspace_revision,
            base_fact_data_revision: manifest.fact_data_revision,
            base_weather_data_revision: manifest.weather_data_revision,
        };
        const markAttempted = (currentBundleId: string) => {
            attemptedBundleIds.current.add(manifest.bundle_id);
            attemptedBundleIds.current.add(currentBundleId);
        };
        const refresh = async () => {
            try {
                for (let attempt = 1; attempt <= MAX_REFRESH_ATTEMPTS && active; attempt += 1) {
                    try {
                        const result = await refreshCurrentBundleWeather(manifest.run_id, request);
                        if (!active || !isPublicDeliveryBundle(result.bundle))
                            return;
                        markAttempted(result.bundle.manifest.bundle_id);
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
                            markAttempted(manifest.bundle_id);
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
                        if (!shouldRetryWeatherRefresh(error) || attempt === MAX_REFRESH_ATTEMPTS)
                            return;
                        await waitForRetry(weatherRetryDelayMs(attempt));
                    }
                }
            }
            finally {
                inFlightBundleIds.current.delete(manifest.bundle_id);
            }
        };
        void refresh();
        return () => {
            active = false;
        };
    }, [bundle, currentStateRef, dispatch, enabled, state.currentSessionId]);
}
