export interface TravelPreset {
    id: string;
    name: string;
    description: string;
    icon: string;
    category: PresetCategory;
    instructions: string;
    constraints: PresetConstraints;
    is_preset: boolean;
    usage_count: number;
    created_at: string;
    updated_at: string;
}
export type PresetCategory = 'custom' | 'culture' | 'food' | 'family' | 'budget' | 'luxury' | 'adventure' | 'photo' | 'weekend' | 'romantic';
export interface PresetConstraints {
    duration?: string;
    budget?: string;
    pace?: string;
    focus_areas?: string[];
    output_style?: string;
}
export interface PresetCreateData {
    name: string;
    description: string;
    icon?: string;
    category?: string;
    instructions: string;
    constraints?: PresetConstraints;
}
export interface PresetUpdateData {
    name?: string;
    description?: string;
    icon?: string;
    category?: string;
    instructions?: string;
    constraints?: PresetConstraints;
}
export interface GenerateInstructionsResult {
    success: boolean;
    data?: {
        name: string;
        description: string;
        instructions: string;
        constraints: PresetConstraints;
        icon: string;
        category: string;
    };
    error_message?: string;
}
export const PRESET_CATEGORY_LABELS: Record<PresetCategory, string> = {
    custom: '自定义',
    culture: '文化',
    food: '美食',
    family: '亲子',
    budget: '经济',
    luxury: '奢华',
    adventure: '探险',
    photo: '摄影',
    weekend: '周末',
    romantic: '浪漫',
};
