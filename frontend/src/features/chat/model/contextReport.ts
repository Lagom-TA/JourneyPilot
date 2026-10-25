import { type ContextReport, type ContextReportCompaction, type ContextReportSection, type ContextReportSectionKey } from "../types/context";
const SECTION_KEYS: readonly ContextReportSectionKey[] = ['hard', 'preference', 'reference'];
function normalizeCompaction(raw: unknown): ContextReportCompaction {
    return { triggered: Boolean(raw && typeof raw === 'object' && (raw as Record<string, unknown>).triggered) };
}
function normalizeSection(raw: unknown): ContextReportSection | null {
    if (!raw || typeof raw !== 'object')
        return null;
    const row = raw as Record<string, unknown>;
    const key = SECTION_KEYS.find((candidate) => candidate === row.key);
    if (!key)
        return null;
    const items = Array.isArray(row.items)
        ? row.items.filter((item): item is string => typeof item === 'string' && item.trim() !== '')
        : [];
    return { key, items };
}
export function normalizeContextReport(raw: unknown): ContextReport | null {
    if (!raw || typeof raw !== 'object')
        return null;
    const row = raw as Record<string, unknown>;
    if (!Array.isArray(row.referenced_sections))
        return null;
    const sections: ContextReportSection[] = [];
    for (const entry of row.referenced_sections) {
        const section = normalizeSection(entry);
        if (!section)
            return null;
        if (section.items.length > 0)
            sections.push(section);
    }
    return { sections, compaction: normalizeCompaction(row.compaction) };
}
