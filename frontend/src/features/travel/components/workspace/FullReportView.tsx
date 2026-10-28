import { getCurrentDeliveryBundle, exportCurrentTripReportPdf } from '../../api/delivery';
import { Download } from 'lucide-react';
import { useApp } from '../../../../app/state/AppContext';
import { apiErrorDetail } from '../../../../lib/apiErrorDetail';
import { formatLocalDate, selectDaySummaries, selectDayTimeline, type DaySummaryVM, type DayTimelineNodeVM } from '../../model/itineraryPresentation';
import { splitLabelledFact } from '../../model/tripDomains';
import { formatTripBudget, formatTripCostSummary } from '../../model/costPresentation';
import { BrandMark } from '../../../../app/components/BrandMark';
import { type PublicDeliveryBundle } from '../../types/delivery';
import { type EntityIntentExplanation } from '../../types/itinerary';
import { DayHeader } from './DayHeader';
import { DayTimeline } from './DayTimeline';
import { LabelledFactList, TripFactReadout } from './TripFactReadout';
import { IntentExplanationList } from './IntentExplanationList';
import { Neatline } from '../../../../components/ui/Neatline';
import { Postmark } from '../../../../components/ui/Postmark';
import { safeHref } from '../../../../lib/safeHref';
import React from 'react';

type ReportDocument = NonNullable<PublicDeliveryBundle['report_projection']['document']>;
type ReportDay = ReportDocument['days'][number];
type ReportBlock = ReportDay['blocks'][number];

function ReportEntryLines({ block }: { block: ReportBlock }) {
  const { facts, notes, segment_lines: segmentLines } = block.details;
  const visibleFacts = facts.filter((fact) => {
    const { label } = splitLabelledFact(fact);
    if (label && ['状态', '可订状态', '价格时效', '数据状态'].includes(label)) return false;
    return !/需要确认|需确认|不可订|需向.*核对|当前尚无|尚未取得|不代表整趟|具体门店现场确认/.test(fact);
  });
  const visibleNotes = notes.filter((note) => !/需要确认|需确认|不可订|核查|核对|尚未|不代表|提前预订|点餐前确认价格|具体门店现场确认/.test(note));
  return (
    <>
      {visibleFacts.length > 0 && (
        <p className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1 break-words text-[11px] leading-5">
          {visibleFacts.map((fact) => {
            const { label, value } = splitLabelledFact(fact);
            return (
              <span key={fact} className="inline-flex min-w-0 items-baseline gap-1">
                {label && <span className="shrink-0 text-ink-muted">{label}</span>}
                <span className="min-w-0 break-words font-medium text-ink-secondary">{value}</span>
              </span>
            );
          })}
        </p>
      )}
      {visibleNotes.map((note) => <p key={note} className="mt-1.5 max-w-[70ch] break-words text-xs leading-5 text-ink-secondary">{note}</p>)}
      {segmentLines.length > 0 && (
        <ol className="mt-2 space-y-1 border-l border-stroke pl-3" aria-label="班次信息">
          {segmentLines.map((line) => <li key={line} className="break-words text-[11px] leading-5 text-ink-secondary">{line}</li>)}
        </ol>
      )}
    </>
  );
}

export function PdfDownloadButton({ bundle, compact = false }: {
  bundle: PublicDeliveryBundle;
  compact?: boolean;
}) {
  const { state, dispatch } = useApp();
  const [status, setStatus] = React.useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [message, setMessage] = React.useState<string | null>(null);
  const loadCurrent = React.useCallback(async () => {
    const current = await getCurrentDeliveryBundle(bundle.manifest.run_id, state.currentSessionId);
    dispatch({ type: 'CONFIRM_DELIVERY_BUNDLE', payload: current });
    dispatch({ type: 'SET_DELIVERABLE_VIEW', payload: 'full_report' });
    return current;
  }, [bundle.manifest.run_id, dispatch, state.currentSessionId]);

  const download = async () => {
    setStatus('loading');
    setMessage(null);
    try {
      const result = await exportCurrentTripReportPdf(bundle, state.currentSessionId);
      if (result.bundleId && result.bundleId !== bundle.manifest.bundle_id) await loadCurrent();
      const url = URL.createObjectURL(result.blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = result.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      setStatus('success');
      setMessage('PDF 已生成。');
    } catch (error) {
      const detail = apiErrorDetail(error);
      if (detail.code === 'report_out_of_date') {
        try {
          await loadCurrent();
          setMessage('行程刚刚更新，已载入最新结果。请再次导出。');
        } catch {
          setMessage('行程刚刚更新，请重新打开当前行程后再导出。');
        }
      } else if (detail.code === 'pdf_temporarily_unavailable') {
        setMessage('PDF 暂时无法生成，请稍后重试。');
      } else {
        setMessage('PDF 生成失败，请检查网络后重试。');
      }
      setStatus('error');
    }
  };

  return (
    <div className={compact ? 'relative min-w-0' : 'min-w-0'}>
      <button
        type="button"
        data-testid="download-current-pdf"
        disabled={status === 'loading'}
        onClick={() => void download()}
        className={compact ? 'journey-view-action' : 'inline-flex min-h-10 items-center justify-center gap-2 rounded-card bg-accent px-3.5 text-xs font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-wait disabled:opacity-65'}
      >
        <Download size={14} aria-hidden />
        {status === 'loading' ? (compact ? '准备中' : '正在准备 PDF') : (compact ? 'PDF' : '导出当前 PDF')}
      </button>
      {message && (compact
        ? <span className="sr-only" role={status === 'error' ? 'alert' : 'status'}>{message}</span>
        : <p role={status === 'error' ? 'alert' : 'status'} className="mt-2 max-w-[36ch] break-words text-[11px] leading-5 text-ink-secondary">{message}</p>)}
    </div>
  );
}

function ReportCover({ bundle, document: report, allowPdf }: {
  bundle: PublicDeliveryBundle;
  document: ReportDocument;
  allowPdf: boolean;
}) {
  const destinations = report.destinations.map((entry) => entry.display_name.trim()).filter(Boolean);
  const dates = report.days.map((day) => day.date).filter((date): date is string => Boolean(date));
  const firstDate = formatLocalDate(dates[0] ?? null);
  const lastDate = formatLocalDate(dates[dates.length - 1] ?? null);
  const dateRange = firstDate && lastDate ? (firstDate === lastDate ? firstDate : `${firstDate} – ${lastDate}`) : firstDate ?? lastDate;
  const costLabel = formatTripCostSummary(report.cost_summary);
  const budgetLabel = formatTripBudget(report.cost_summary);
  const readouts: Array<{ label: string; value: string }> = [
    ...(destinations.length > 0 ? [{ label: '目的地', value: destinations.join(' · ') }] : []),
    ...(dateRange ? [{ label: '行程期间', value: dateRange }] : []),
    { label: '天数', value: `${report.duration_days} 天` },
    ...(costLabel ? [{ label: '费用', value: costLabel }] : []),
    ...(budgetLabel ? [{ label: '预算', value: budgetLabel }] : []),
  ];
  return (
    <header data-testid="report-cover" className="report-cover relative px-5 py-7 sm:px-8 sm:py-9">
      <Neatline />
      <div className="relative z-10 flex min-w-0 flex-wrap items-start justify-between gap-x-6 gap-y-5">
        <div className="min-w-0 flex-1 basis-[22rem]">
          <div className="flex items-center gap-2.5">
            <BrandMark size={20} className="shrink-0" />
            <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-ink-muted">JOURNEYPILOT · 旅行刊物</p>
          </div>
          <h1 className="mt-5 max-w-[22ch] break-words text-[30px] font-semibold leading-[1.22] tracking-[-0.022em] text-ink sm:text-[38px]">{report.title}</h1>
          <p className="mt-4 max-w-[58ch] break-words text-[15px] leading-7 text-ink-secondary">{report.overview}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-5">
          {allowPdf && <PdfDownloadButton bundle={bundle} />}
          <Postmark generatedAt={bundle.report_projection.generated_at} />
        </div>
      </div>
      <dl className="relative z-10 mt-7 grid gap-x-6 gap-y-4 border-t border-stroke pt-5 sm:grid-cols-2 lg:grid-cols-4">
        {readouts.map((entry) => <TripFactReadout key={entry.label} {...entry} />)}
      </dl>
    </header>
  );
}

function ReportTimelineSupplement({ block, node }: { block: ReportBlock; node: DayTimelineNodeVM }) {
  const reportSummary = block.summary.trim();
  const nodeSummary = node.summary?.trim() ?? '';
  const summaryIsAdditional = reportSummary && reportSummary !== block.title.trim() && reportSummary !== nodeSummary;
  const intentExplanations = Array.isArray(block.details.intent_explanations)
    ? block.details.intent_explanations.filter((item): item is EntityIntentExplanation => Boolean(
      item && typeof item === 'object' && typeof (item as EntityIntentExplanation).label === 'string' && typeof (item as EntityIntentExplanation).explanation === 'string',
    ))
    : [];
  return (
    <div data-testid={`report-timeline-supplement-${node.key}`} className="min-w-0">
      {summaryIsAdditional && <p className="mt-1 max-w-[68ch] break-words text-sm leading-6 text-ink-secondary">{reportSummary}</p>}
      <ReportEntryLines block={block} />
      <IntentExplanationList items={intentExplanations} />
    </div>
  );
}

function ReportDaySection({ day, summary, nodes }: {
  day: ReportDay;
  summary: DaySummaryVM | null;
  nodes: readonly DayTimelineNodeVM[];
}) {
  const blocks = React.useMemo(() => new Map(day.blocks.map((block) => [block.details.entry_id, block])), [day.blocks]);
  if (!summary) return null;
  return (
    <section data-testid={`report-day-${day.day_id}`} className="border-t border-stroke py-7 first:border-t-0 first:pt-6 sm:py-8" aria-labelledby={`delivery-day-report-${day.day_id}`}>
      <DayHeader dayId={`report-${day.day_id}`} day={summary.day} dateLabel={summary.dateLabel} weekdayLabel={summary.weekdayLabel} destinationLabel={summary.destinationLabel} theme={summary.theme} weather={summary.weather} />
      <DayTimeline nodes={nodes} renderSupplement={(node) => {
        const block = blocks.get(node.key);
        return block ? <ReportTimelineSupplement block={block} node={node} /> : null;
      }} />
    </section>
  );
}

export function FullReportView({ bundle, allowPdf = true }: {
  bundle: PublicDeliveryBundle;
  allowPdf?: boolean;
}) {
  const document = bundle.report_projection.document;
  if (!document) return null;
  const summaries = selectDaySummaries(bundle);
  const summariesByDayId = new Map(summaries.map((summary) => [summary.dayId, summary]));
  const seenReferences = new Set<string>();
  const references = bundle.source_index.content.citations.flatMap((citation) => citation.sources).filter((source) => {
    if (seenReferences.has(source.source_record_id)) return false;
    seenReferences.add(source.source_record_id);
    return true;
  });

  return (
    <article data-testid="full-report" className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-7 sm:py-8">
      <ReportCover bundle={bundle} document={document} allowPdf={allowPdf} />

      <nav className="report-toc" aria-label="阅读版目录">
        <span>目录</span>
        {document.highlights.length > 0 && <a href="#report-highlights-heading">行程总览</a>}
        <a href="#report-days">每日安排</a>
        {references.length > 0 && <a href="#report-references">参考资料</a>}
      </nav>

      {document.highlights.length > 0 && (
        <section data-testid="report-highlights" className="border-b border-stroke py-7" aria-labelledby="report-highlights-heading">
          <h2 id="report-highlights-heading" className="font-display text-xl font-semibold text-ink">全程亮点</h2>
          <div className="mt-4"><LabelledFactList facts={document.highlights} /></div>
        </section>
      )}

      <div id="report-days">
        {document.days.map((day) => (
          <ReportDaySection key={day.day_id} day={day} summary={summariesByDayId.get(day.day_id) ?? null} nodes={selectDayTimeline(bundle, day.day_id)} />
        ))}
      </div>

      {references.length > 0 && (
        <footer id="report-references" className="report-references" aria-labelledby="report-references-heading">
          <p>REFERENCES</p>
          <h2 id="report-references-heading">参考资料</h2>
          <ol>
            {references.map((source, index) => {
              const href = safeHref(source.canonical_url);
              return (
                <li key={source.source_record_id}>
                  <span>{String(index + 1).padStart(2, '0')}</span>
                  <div>
                    <h3>{href ? <a href={href} target="_blank" rel="noreferrer">{source.title}</a> : source.title}</h3>
                    {source.public_excerpt && <p>{source.public_excerpt}</p>}
                  </div>
                </li>
              );
            })}
          </ol>
        </footer>
      )}
    </article>
  );
}
