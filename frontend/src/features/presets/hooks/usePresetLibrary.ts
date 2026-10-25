import { useState, useEffect, useCallback } from "react";
import { listPresets } from "../api/presets";
import { type TravelPreset } from "../types/preset";
import { describeRequestFailure, type RequestFailure } from "../../../lib/requestFailureMessage";
export function usePresetLibrary() {
    const [presets, setPresets] = useState<TravelPreset[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState<RequestFailure | null>(null);
    const loadPresets = useCallback(async () => {
        setLoading(true);
        setLoadError(null);
        try {
            const result = await listPresets();
            setPresets(result);
        }
        catch (err) {
            setPresets([]);
            setLoadError(describeRequestFailure(err, '读取', '旅行风格'));
        }
        finally {
            setLoading(false);
        }
    }, []);
    useEffect(() => {
        void loadPresets();
    }, [loadPresets]);
    return { presets, loading, loadError, loadPresets };
}
