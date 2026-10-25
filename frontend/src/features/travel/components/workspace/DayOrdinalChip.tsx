export function dayAccent(day: number): string {
    const index = Math.max(0, day - 1) % 10;
    return `var(--chart-day-${index + 1})`;
}
export function DayOrdinalChip({ day }: {
    day: number;
}) {
    const accent = dayAccent(day);
    return (<p data-day-chip className="inline-flex shrink-0 items-center rounded-label border-[1.5px] px-2 py-[3px] font-mono text-[12px] font-semibold tracking-[0.06em] text-ink" style={{
            borderColor: accent,
            backgroundColor: `color-mix(in srgb, ${accent} 8%, transparent)`,
        }}>
      第 {day} 天
    </p>);
}
