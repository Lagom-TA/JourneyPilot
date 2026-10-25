import { cn } from "../../../../lib/utils";
import { READOUT_LABEL } from "../../../../lib/typography";
import { RollingNumber } from "../../../../components/ui/RollingNumber";
import { InspectRow, InspectSectionTitle } from "../../../../components/ui/InspectHint";
import { type CostLedgerBreakdown, type CostLedgerNotice, type CostLedgerSaving, type CostLedgerTile, type CostLedgerView } from "../../model/costLedger";
import React from 'react';
const TILE_VALUE = 'text-[13px] font-semibold tabular-nums';
const Tile: React.FC<{
    tile: CostLedgerTile;
}> = ({ tile }) => (<div data-ledger-field={tile.field} data-ledger-display={tile.estimated ? `≈${tile.display}` : tile.display} className="flex min-w-0 flex-col items-center gap-1 rounded-card bg-surface px-1.5 py-2">
    {tile.value == null ? (<span className={cn(TILE_VALUE, tile.accent ? 'text-accent' : 'text-ink')}>{tile.display}</span>) : (<RollingNumber value={tile.value} format={() => tile.display} prefix={tile.estimated ? '≈' : undefined} className={cn(TILE_VALUE, tile.accent ? 'text-accent' : 'text-ink')}/>)}
    <span className="max-w-full truncate text-[11px] text-ink-muted">{tile.label}</span>
  </div>);
const Breakdown: React.FC<{
    breakdown: CostLedgerBreakdown;
}> = ({ breakdown }) => (<section data-ledger-field={breakdown.field} className="flex flex-col gap-2">
    <InspectSectionTitle>按环节</InspectSectionTitle>
    <ul className="flex flex-col gap-2">
      {breakdown.rows.map((row) => (<li key={row.key} className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="min-w-0 truncate text-[11px] text-ink">{row.label}</span>
            <span className="shrink-0 font-mono text-[11px] tabular-nums text-ink-secondary">
              {row.tokens} · {row.cost}
            </span>
          </div>
          <div className="h-1 overflow-hidden rounded-full bg-highlight">
            <div className="h-full rounded-full bg-accent" style={{ width: `${Math.max(2, Math.round(row.barShare * 100))}%` }}/>
          </div>
          <span className="font-mono text-[11px] tabular-nums text-ink-muted">
            {row.calls}× · {row.latency}
          </span>
        </li>))}
    </ul>
    {breakdown.rest > 0 && (<span className="text-[11px] text-ink-muted">另有 {breakdown.rest} 个环节未列出</span>)}
  </section>);
const Saving: React.FC<{
    saving: CostLedgerSaving;
}> = ({ saving }) => (<section data-ledger-field={saving.field} className="flex flex-col gap-1 rounded-card bg-surface px-3 py-2">
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-[11px] text-ink">工具说明用量节省</span>
      <span className="shrink-0 font-mono text-[11px] font-semibold tabular-nums text-success">
        {saving.ratio}
      </span>
    </div>
    <span className="font-mono text-[11px] tabular-nums text-ink-muted">
      {saving.savedTokens} · {saving.exposure}
    </span>
    <span className="text-[11px] text-ink-muted">{saving.modeLabel}</span>
  </section>);
const Notice: React.FC<{
    notice: CostLedgerNotice;
}> = ({ notice }) => (<p data-ledger-field={notice.field} className={cn('rounded-card px-3 py-2 text-xs leading-relaxed', notice.tone === 'warning'
        ? 'bg-[color-mix(in_srgb,var(--color-warning)_8%,var(--color-surface))] text-ink-secondary'
        : 'bg-surface text-ink-secondary')}>
    {notice.text}
  </p>);
export const CostLedger: React.FC<{
    view: CostLedgerView;
}> = ({ view }) => (<div data-testid="cost-ledger" data-ledger-source={view.source} className="flex max-h-[min(70vh,520px)] flex-col gap-3 overflow-y-auto p-4">
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-[13px] font-semibold text-ink">本轮模型用量</span>
      {view.source === 'live' && (<span className={cn(READOUT_LABEL, 'shrink-0 text-ink-muted')}>LIVE</span>)}
    </div>

    <div className={cn('grid gap-1.5', view.tiles.length >= 4 ? 'grid-cols-4' : 'grid-cols-3')}>
      {view.tiles.map((tile) => (<Tile key={tile.field} tile={tile}/>))}
    </div>

    {view.activeLabel && (<p className="text-[11px] leading-relaxed text-ink-secondary">
        正在累计 · {view.activeLabel}
      </p>)}

    <div className="flex flex-col gap-1">
      {view.rows.map((row) => (<div key={row.field} data-ledger-field={row.field}>
          <InspectRow label={row.label} value={row.display}/>
        </div>))}
    </div>

    {view.breakdown && <Breakdown breakdown={view.breakdown}/>}
    {view.saving && <Saving saving={view.saving}/>}
    {view.notices.map((notice) => (<Notice key={`${notice.field}:${notice.tone}`} notice={notice}/>))}


    <p className="text-xs leading-relaxed text-ink-secondary">
      每一次模型调用都逐条落进运行台账，这里的数字是那些行的合计。
    </p>
  </div>);
