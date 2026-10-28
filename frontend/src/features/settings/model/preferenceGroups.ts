import { type PreferenceOptionGroup, type UserProfile } from "../types/profile";
export interface PreferenceChipGroup {
    key: string;
    label: string;
    multi: boolean;
    chips: Array<{
        option: string;
        selected: boolean;
    }>;
}
export type PreferenceSelections = Record<string, string[]>;
export function readPreferenceSelections(groups: PreferenceOptionGroup[], profile: UserProfile | null): PreferenceSelections {
    const stored = (profile?.preferences ?? {}) as Record<string, unknown>;
    const selections: PreferenceSelections = {};
    for (const group of groups) {
        const value = stored[group.key];
        if (Array.isArray(value))
            selections[group.key] = value.map(String);
        else if (typeof value === 'string' && value.trim())
            selections[group.key] = [value];
        else
            selections[group.key] = [];
    }
    return selections;
}
export function preferenceChipGroups(groups: PreferenceOptionGroup[], selections: PreferenceSelections): PreferenceChipGroup[] {
    return groups.filter((group) => !group.key.toLowerCase().includes('budget') && !group.label.includes('预算')).map((group) => {
        const chosen = selections[group.key] ?? [];
        return {
            key: group.key,
            label: group.label,
            multi: group.multi,
            chips: group.options.map((option) => ({ option, selected: chosen.includes(option) })),
        };
    });
}
export function togglePreferenceOption(group: PreferenceOptionGroup, selections: PreferenceSelections, option: string): PreferenceSelections {
    const current = selections[group.key] ?? [];
    const updated = group.multi
        ? current.includes(option)
            ? current.filter((value) => value !== option)
            : [...current, option]
        : current.includes(option)
            ? []
            : [option];
    return { ...selections, [group.key]: updated };
}
export function buildPreferencePayload(groups: PreferenceOptionGroup[], selections: PreferenceSelections): Record<string, unknown> {
    const payload: Record<string, unknown> = {};
    for (const group of groups) {
        const values = selections[group.key] ?? [];
        payload[group.key] = group.multi ? values : (values[0] ?? '');
    }
    return payload;
}
