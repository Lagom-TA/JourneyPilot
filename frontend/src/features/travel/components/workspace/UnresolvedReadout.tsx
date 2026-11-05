import { isUnscheduledItem } from '../../model/itineraryNavigation';

export function UnresolvedReadout({ items, all = false }: { items: readonly string[]; all?: boolean }) {
  if (items.length === 0) return null;
  const visible = all ? [] : items.filter(isUnscheduledItem);
  const remaining = all ? items : items.filter((item) => !isUnscheduledItem(item));
  return (
    <section className="journey-unresolved" aria-label="尚未安排与待完善事项">
      {visible.length > 0 && <ul>{visible.map((text) => <li key={text}>{text}</li>)}</ul>}
      {remaining.length > 0 && (
        <details>
          <summary>{all ? '尚未安排与待完善事项' : '待完善的信息'} <span>{remaining.length}</span></summary>
          <ul>{remaining.map((text) => <li key={text}>{text}</li>)}</ul>
        </details>
      )}
    </section>
  );
}
