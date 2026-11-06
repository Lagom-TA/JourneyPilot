import { getCurrentDeliveryBundle, exportCurrentTripReportPdf } from '../../api/delivery';
import { Download } from 'lucide-react';
import { useApp } from '../../../../app/state/AppContext';
import { apiErrorDetail } from '../../../../lib/apiErrorDetail';
import { formatLocalDate, selectDaySummaries, selectDayTimeline, type DaySummaryVM, type DayTimelineNodeVM } from '../../model/itineraryPresentation';
import { splitLabelledFact } from '../../model/tripDomains';
import { formatTripCostSummary } from '../../model/costPresentation';
import { type PublicDeliveryBundle } from '../../types/delivery';
import { DayHeader } from './DayHeader';
import { DayTimeline } from './DayTimeline';
import { LabelledFactList } from './TripFactReadout';
import { unresolvedForDay } from '../../model/itineraryNavigation';
import { UnresolvedReadout } from './UnresolvedReadout';
import { EntitySourceList } from './EntitySourceList';
import { safeHref } from '../../../../lib/safeHref';
import { splitTitleClauses } from '../../../../lib/titleClauses';
import React from 'react';

type ReportDocument = NonNullable<PublicDeliveryBundle['report_projection']['document']>;
type ReportDay = ReportDocument['days'][number];
type ReportBlock = ReportDay['blocks'][number];

function ReportEntryLines({ block }: { block: ReportBlock }) {
  const { facts, notes, segment_lines: segmentLines } = block.details;
  return (
    <>
      {facts.length > 0 && (
        <p className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1 break-words text-[11px] leading-5">
          {facts.map((fact) => {
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
      {notes.map((note) => <p key={note} className="mt-1.5 max-w-[70ch] break-words text-xs leading-5 text-ink-secondary">{note}</p>)}
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
        ? <span className="pdf-export-feedback" role={status === 'error' ? 'alert' : 'status'}>{message}</span>
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
  const dateText = dates.length ? `${dates[0]} 至 ${dates[dates.length - 1]}` : `${report.duration_days} 天`;
  const identityOverview = `${dateText}，前往${destinations.join('、')}的旅行计划。`;
  return (
    <header data-testid="report-cover" className="report-cover">
      <h1>{splitTitleClauses(report.title).map((clause, clauseIndex) => (
        <span key={clauseIndex} className="report-title-clause">
          {clause.split(/([零一二三四五六七八九十百〇\d]+(?:天|日|晚))/g).map((part, index) => (
            <span key={index} className={/[零一二三四五六七八九十百〇\d]+(?:天|日|晚)/.test(part) ? 'report-title-unit' : undefined}>{part}</span>
          ))}
        </span>
      ))}</h1>
      <div className="report-cover-meta">
        {destinations.map((name) => <span key={name}>{name}</span>)}
        {dateRange && <span>{dateRange}</span>}
        <span>{report.duration_days} 天</span>
      </div>
      {report.overview !== identityOverview && <p className="report-cover-overview">{report.overview}</p>}
      {costLabel && <p className="report-cover-cost">{costLabel}</p>}
      {allowPdf && <PdfDownloadButton bundle={bundle} />}
    </header>
  );
}

function ReportTimelineSupplement({ block, node, bundle }: { block: ReportBlock; node: DayTimelineNodeVM; bundle: PublicDeliveryBundle }) {
  return (
    <div data-testid={`report-timeline-supplement-${node.key}`} className="min-w-0">
      <ReportEntryLines block={block} />
      <EntitySourceList bundle={bundle} entityId={node.entityId} />
    </div>
  );
}

function ReportDaySection({ day, summary, nodes, bundle }: {
  day: ReportDay;
  summary: DaySummaryVM | null;
  nodes: readonly DayTimelineNodeVM[];
  bundle: PublicDeliveryBundle;
}) {
  const blocks = React.useMemo(() => new Map(day.blocks.map((block) => [block.details.entry_id, block])), [day.blocks]);
  if (!summary) return null;
  return (
    <section data-testid={`report-day-${day.day_id}`} className="border-t border-stroke py-7 first:border-t-0 first:pt-6 sm:py-8" aria-labelledby={`delivery-day-report-${day.day_id}`}>
      <DayHeader dayId={`report-${day.day_id}`} day={summary.day} dateLabel={summary.dateLabel} weekdayLabel={summary.weekdayLabel} destinationLabel={summary.destinationLabel} theme={summary.theme} weather={summary.weather} />
      <UnresolvedReadout items={unresolvedForDay(bundle, day.day_id)} />
      <DayTimeline nodes={nodes} renderSupplement={(node) => {
        const block = blocks.get(node.key);
        return block ? <ReportTimelineSupplement block={block} node={node} bundle={bundle} /> : null;
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
  const assignedUnresolved = new Set(bundle.workspace.itinerary.day_plans.flatMap((day) => unresolvedForDay(bundle, day.day_id)));
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
          <ReportDaySection key={day.day_id} day={day} summary={summariesByDayId.get(day.day_id) ?? null} nodes={selectDayTimeline(bundle, day.day_id)} bundle={bundle} />
        ))}
      </div>

      <UnresolvedReadout items={document.unresolved.filter((item) => !assignedUnresolved.has(item))} all />

      {references.length > 0 && (
        <footer id="report-references" className="report-references" aria-labelledby="report-references-heading">
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
