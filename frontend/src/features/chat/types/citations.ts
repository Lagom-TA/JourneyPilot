export interface CitationSource {
    title?: string;
    url?: string;
    sourceName?: string;
    snippet?: string;
    authorityLabel?: string;
    retrievedAt?: string;
}
export interface FinalAnswerCitation {
    citationId: string;
    claimText?: string;
    sources: CitationSource[];
}
export type InformationAnnotationKind = 'time_sensitive' | 'seasonal_reference' | 'safety_reference';
export interface InformationAnnotation {
    annotationId: string;
    kind: InformationAnnotationKind;
    label: string;
    detail: string;
}
