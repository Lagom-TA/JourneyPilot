export interface ContextReportCompaction {
    triggered: boolean;
}
export type ContextReportSectionKey = 'hard' | 'preference' | 'reference';
export interface ContextReportSection {
    key: ContextReportSectionKey;
    items: string[];
}
export interface ContextReport {
    sections: ContextReportSection[];
    compaction: ContextReportCompaction;
}
export interface ContextCompactionEvent {
    id: string;
    source: 'manual' | 'automatic';
    occurredAt: string;
    summary: string;
    keyConstraints: string[];
}
