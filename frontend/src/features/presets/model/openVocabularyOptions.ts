export function focusAreaChips(suggestions: readonly string[], stored: readonly string[]): string[] {
    const extras = stored.filter((value) => value && !suggestions.includes(value));
    return [...suggestions, ...Array.from(new Set(extras))];
}
export function selectValuesIncludingStored(values: readonly string[], stored: string | null | undefined): string[] {
    if (!stored || values.includes(stored))
        return [...values];
    return [...values, stored];
}
