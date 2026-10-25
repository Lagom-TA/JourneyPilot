const DATE_TAIL = /^\d{1,2}\/\d{1,2}(?:–\d{1,2}\/\d{1,2})?$/;
const ROUTE_ARROW = ' → ';
const FIELD_SEPARATOR = ' · ';
export type ParsedSessionTitle = {
    kind: 'trip';
    origin: string | null;
    destination: string;
    dates: string | null;
} | {
    kind: 'plain';
    text: string;
};
export function parseSessionTitle(title: string): ParsedSessionTitle {
    const text = title.trim();
    if (!text)
        return { kind: 'plain', text: title };
    let head = text;
    let dates: string | null = null;
    const lastSeparator = text.lastIndexOf(FIELD_SEPARATOR);
    if (lastSeparator > 0) {
        const tail = text.slice(lastSeparator + FIELD_SEPARATOR.length);
        if (DATE_TAIL.test(tail)) {
            head = text.slice(0, lastSeparator);
            dates = tail;
        }
    }
    const arrowAt = head.indexOf(ROUTE_ARROW);
    const origin = arrowAt > 0 ? head.slice(0, arrowAt).trim() : null;
    const destination = arrowAt > 0 ? head.slice(arrowAt + ROUTE_ARROW.length).trim() : head;
    if (!origin && !dates)
        return { kind: 'plain', text };
    if (!destination)
        return { kind: 'plain', text };
    return { kind: 'trip', origin, destination, dates };
}
