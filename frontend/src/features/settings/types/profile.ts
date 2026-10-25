export interface UserProfile {
    display_name: string;
    preferences: Record<string, unknown>;
}
export interface PreferenceOptionGroup {
    key: string;
    label: string;
    multi: boolean;
    options: string[];
}
