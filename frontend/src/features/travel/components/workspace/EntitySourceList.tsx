import { type PublicDeliveryBundle } from '../../types/delivery';
import { safeHref } from '../../../../lib/safeHref';

export function EntitySourceList({ bundle, entityId }: { bundle: PublicDeliveryBundle; entityId: string }) {
  const citations = bundle.source_index.content.citations.filter((item) => item.entity_ref.entity_id === entityId && item.sources.length > 0);
  if (citations.length === 0) return null;
  type Source = typeof citations[number]['sources'][number];
  const sources = new Map<string, { source: Source; labels: Set<string> }>();
  for (const citation of citations) {
    for (const source of citation.sources) {
      const entry = sources.get(source.source_record_id) ?? { source, labels: new Set<string>() };
      citation.supported_values.forEach((value) => entry.labels.add(value.label));
      sources.set(source.source_record_id, entry);
    }
  }
  return (
    <details className="journey-entity-sources">
      <summary>资料来源</summary>
      <ul>
        {[...sources.values()].map(({ source, labels }) => {
          const href = safeHref(source.canonical_url);
          return (
            <li key={source.source_record_id} data-source-record={source.source_record_id}>
              {labels.size > 0 && <span>{[...labels].join(' · ')}</span>}
              {href ? <a href={href} target="_blank" rel="noreferrer">{source.title}</a> : <p>{source.title}</p>}
            </li>
          );
        })}
      </ul>
    </details>
  );
}
