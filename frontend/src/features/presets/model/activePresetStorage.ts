const ACTIVE_PRESET_KEY = 'journeypilot.active-preset';
export interface StoredActivePreset {
    id: string;
    name: string;
}
export const readStoredActivePreset = (): StoredActivePreset | null => {
    try {
        const raw = localStorage.getItem(ACTIVE_PRESET_KEY);
        if (!raw)
            return null;
        const parsed: unknown = JSON.parse(raw);
        if (typeof parsed !== 'object' || parsed === null)
            return null;
        const { id, name } = parsed as Record<string, unknown>;
        if (typeof id !== 'string' || id.trim() === '')
            return null;
        return { id, name: typeof name === 'string' ? name : '' };
    }
    catch {
        return null;
    }
};
export const writeStoredActivePreset = (preset: StoredActivePreset | null): void => {
    try {
        if (!preset) {
            localStorage.removeItem(ACTIVE_PRESET_KEY);
            return;
        }
        localStorage.setItem(ACTIVE_PRESET_KEY, JSON.stringify(preset));
    }
    catch {
        // 本地存储不可用时仍可使用当前选择。
    }
};
