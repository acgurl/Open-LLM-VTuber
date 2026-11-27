import { memo, useEffect, useMemo, useRef, useState, type MouseEvent } from 'react';
import { useTranslation } from 'react-i18next';
import type { ToolEntry } from '../stores/chat';
import { useSettings } from '../stores/settings';
import {
  getKbToolKind,
  parseKbDocumentChunksResult,
  parseKbDocumentsResult,
  parseKbInput,
  parseKbSearchResult,
  type KbCitationItem,
  type KbDocumentCatalogItem,
  type KbDocumentChunkItem,
  type KbToolInput,
} from '../utils/kbSearch';
import { ToolCallCard } from './ToolCallCard';
import { BookOpenIcon, CalendarIcon, ExternalLinkIcon, FileTextIcon } from './icons';

const DEFAULT_VISIBLE = 3;
const HOLD_MS = 420;

function formatPageLabel(
  t: (key: string, opts?: Record<string, unknown>) => string,
  start?: number,
  end?: number,
): string | undefined {
  if (!start) return undefined;
  if (end && end > start) return t('kb.pageRange', { start, end });
  return t('kb.pageSingle', { page: start });
}

function formatInputSubtitle(
  t: (key: string, opts?: Record<string, unknown>) => string,
  input: KbToolInput | null,
  fallbackTool: string,
): string {
  if (!input) return fallbackTool;
  if (input.query) return t('kb.queryPrefix', { query: input.query });
  if (input.page) {
    return input.pageEnd && input.pageEnd > input.page
      ? t('kb.locatingPageRange', { start: input.page, end: input.pageEnd })
      : t('kb.locatingPage', { page: input.page });
  }
  if (input.docId) return input.docId;
  return fallbackTool;
}

function formatRunningFilters(input: KbToolInput | null): string[] {
  if (!input) return [];
  const tags: string[] = [];
  if (input.role) tags.push(input.role);
  if (input.campus) tags.push(input.campus);
  if (input.docType) tags.push(...input.docType);
  if (input.assistant) tags.push(input.assistant);
  return tags;
}

export const KbSearchCard = memo(function KbSearchCard({ entry }: { entry: ToolEntry }) {
  const { t } = useTranslation();
  const kind = getKbToolKind(entry.tool_name) ?? 'search';
  const lastInputRef = useRef<KbToolInput | null>(null);

  const runningInput = useMemo(
    () => (entry.status === 'running' ? parseKbInput(entry.content) : null),
    [entry.status, entry.content],
  );
  if (runningInput) {
    lastInputRef.current = runningInput;
  }

  const searchData = useMemo(
    () => (entry.status === 'completed' && kind === 'search' ? parseKbSearchResult(entry.content) : null),
    [entry.status, entry.content, kind],
  );
  const chunksData = useMemo(
    () =>
      entry.status === 'completed' && kind === 'chunks'
        ? parseKbDocumentChunksResult(entry.content)
        : null,
    [entry.status, entry.content, kind],
  );
  const docsData = useMemo(
    () =>
      entry.status === 'completed' && kind === 'documents'
        ? parseKbDocumentsResult(entry.content)
        : null,
    [entry.status, entry.content, kind],
  );

  // Completed payload isn't valid KB JSON (e.g. unexpected string): fall back cleanly.
  if (
    entry.status === 'completed' &&
    ((kind === 'search' && !searchData) ||
      (kind === 'chunks' && !chunksData) ||
      (kind === 'documents' && !docsData))
  ) {
    return <ToolCallCard entry={entry} />;
  }

  const itemCount = searchData
    ? searchData.results.length
    : chunksData
      ? chunksData.chunks.length
      : docsData
        ? docsData.documents.length
        : 0;

  const hasBody =
    entry.status === 'error' ||
    (entry.status === 'running' && formatRunningFilters(runningInput).length > 0) ||
    (entry.status === 'completed' && itemCount > 0);

  return (
    <KbSearchCardView
      entry={entry}
      kind={kind}
      runningInput={runningInput}
      lastInput={lastInputRef.current}
      searchData={searchData}
      chunksData={chunksData}
      docsData={docsData}
      hasBody={hasBody}
      t={t}
    />
  );
});

interface ViewProps {
  entry: ToolEntry;
  kind: 'search' | 'chunks' | 'documents';
  runningInput: KbToolInput | null;
  lastInput: KbToolInput | null;
  searchData: ReturnType<typeof parseKbSearchResult>;
  chunksData: ReturnType<typeof parseKbDocumentChunksResult>;
  docsData: ReturnType<typeof parseKbDocumentsResult>;
  hasBody: boolean;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

function KbSearchCardView({
  entry,
  kind,
  runningInput,
  lastInput,
  searchData,
  chunksData,
  docsData,
  hasBody,
  t,
}: ViewProps) {
  const autoCollapse = useSettings((s) => s.autoCollapseToolCards);
  const [open, setOpen] = useState(
    () => hasBody && (entry.status === 'running' || !autoCollapse),
  );
  const [showAll, setShowAll] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());
  const wasRunning = useRef(entry.status === 'running');
  const prevAutoCollapse = useRef(autoCollapse);
  const touched = useRef(false);
  const holdTimer = useRef(0);

  useEffect(() => {
    window.clearTimeout(holdTimer.current);
    const running = entry.status === 'running';
    if (!hasBody) {
      setOpen(false);
    } else if (!touched.current) {
      if (running) {
        setOpen(true);
      } else if (wasRunning.current && autoCollapse) {
        holdTimer.current = window.setTimeout(() => setOpen(false), HOLD_MS);
      } else {
        setOpen(!autoCollapse);
      }
    }
    wasRunning.current = running;
    prevAutoCollapse.current = autoCollapse;
    return () => window.clearTimeout(holdTimer.current);
  }, [entry.status, hasBody, autoCollapse]);

  const toggleCard = () => {
    if (!hasBody) return;
    touched.current = true;
    window.clearTimeout(holdTimer.current);
    setOpen((v) => !v);
  };

  const toggleItem = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const title =
    kind === 'chunks'
      ? t('kb.titleChunks')
      : kind === 'documents'
        ? t('kb.titleDocuments')
        : t('kb.titleSearch');

  let subtitle = '';
  if (entry.status === 'running') {
    subtitle = formatInputSubtitle(t, runningInput, entry.tool_name);
  } else if (entry.status === 'error') {
    const errInput = parseKbInput(entry.content) ?? lastInput;
    subtitle = formatInputSubtitle(t, errInput, entry.tool_name);
  } else if (searchData) {
    const q = searchData.query ?? lastInput?.query;
    subtitle = q ? `「${q}」` : entry.tool_name;
  } else if (chunksData) {
    subtitle = chunksData.fileName ?? chunksData.title;
  } else if (docsData) {
    subtitle = t('kb.docsCount', { count: docsData.count });
  }

  let badgeText = '';
  let badgeTone: 'pending' | 'ok' | 'related' | 'muted' | 'error' = 'muted';
  if (entry.status === 'running') {
    badgeTone = 'pending';
    badgeText =
      kind === 'chunks'
        ? t('kb.readingChunks')
        : kind === 'documents'
          ? t('kb.listingDocs')
          : t('kb.searching');
  } else if (entry.status === 'error') {
    badgeTone = 'error';
    badgeText = t('kb.error');
  } else if (searchData) {
    if (searchData.placeAnswer && searchData.results.length === 0) {
      badgeTone = 'ok';
      badgeText = t('kb.placeDirect');
    } else if (searchData.results.length > 0) {
      if (searchData.answerMode === 'related') {
        badgeTone = 'related';
        badgeText = t('kb.relatedCount', { count: searchData.results.length });
      } else {
        badgeTone = 'ok';
        badgeText = t('kb.hitCount', { count: searchData.results.length });
      }
    } else if (searchData.missingVersionYear) {
      badgeTone = 'muted';
      badgeText = t('kb.missingYear', { year: searchData.missingVersionYear });
    } else {
      badgeTone = 'muted';
      badgeText = t('kb.noHit');
    }
  } else if (chunksData) {
    badgeTone = 'ok';
    badgeText = t('kb.chunksRead', { count: chunksData.chunks.length });
  } else if (docsData) {
    badgeTone = 'ok';
    badgeText = t('kb.docsCount', { count: docsData.count });
  }

  const runningFilters = entry.status === 'running' ? formatRunningFilters(runningInput) : [];
  const interrupted = entry.status === 'error' && entry.content.trim().startsWith('Input:');
  const errorText = interrupted
    ? t('kb.interrupted')
    : entry.content.replace(/^Error:\s*/i, '').trim();

  return (
    <div className={`tool-card kb-card status-${entry.status}`}>
      {hasBody ? (
        <button
          type="button"
          className="tool-head kb-head"
          aria-expanded={open}
          aria-label={t('kb.toggleCard')}
          onClick={toggleCard}
        >
          <CardHeaderContent
            title={title}
            subtitle={subtitle}
            tookMs={searchData?.tookMs}
            badgeText={badgeText}
            badgeTone={badgeTone}
            showChevron
          />
        </button>
      ) : (
        <div className="tool-head kb-head static">
          <CardHeaderContent
            title={title}
            subtitle={subtitle}
            tookMs={searchData?.tookMs}
            badgeText={badgeText}
            badgeTone={badgeTone}
            showChevron={false}
          />
        </div>
      )}

      {hasBody && (
        <div className={`collapsible${open ? ' open' : ''}`} aria-hidden={!open}>
          <div className="collapsible-inner">
            <div className="kb-body">
              {entry.status === 'running' && runningFilters.length > 0 && (
                <div className="kb-meta-row kb-running-filters">
                  {runningFilters.map((f) => (
                    <span key={f} className="kb-tag type">
                      {f}
                    </span>
                  ))}
                </div>
              )}

              {entry.status === 'error' && <div className="kb-error">{errorText}</div>}

              {searchData && searchData.results.length > 0 && (
                <SearchResultsBody
                  results={searchData.results}
                  degraded={searchData.degraded}
                  showAll={showAll}
                  onToggleAll={() => setShowAll((v) => !v)}
                  expandedIds={expandedIds}
                  onToggleItem={toggleItem}
                  t={t}
                />
              )}

              {chunksData && chunksData.chunks.length > 0 && (
                <ChunksBody
                  data={chunksData}
                  showAll={showAll}
                  onToggleAll={() => setShowAll((v) => !v)}
                  expandedIds={expandedIds}
                  onToggleItem={toggleItem}
                  t={t}
                />
              )}

              {docsData && docsData.documents.length > 0 && (
                <DocumentsBody
                  documents={docsData.documents}
                  showAll={showAll}
                  onToggleAll={() => setShowAll((v) => !v)}
                  t={t}
                />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CardHeaderContent({
  title,
  subtitle,
  tookMs,
  badgeText,
  badgeTone,
  showChevron,
}: {
  title: string;
  subtitle: string;
  tookMs?: number;
  badgeText: string;
  badgeTone: 'pending' | 'ok' | 'related' | 'muted' | 'error';
  showChevron: boolean;
}) {
  return (
    <>
      <span className="kb-glyph" aria-hidden="true">
        <BookOpenIcon />
      </span>
      <div className="kb-titles">
        <div className="kb-title-row">
          <strong className="kb-name">{title}</strong>
          {tookMs !== undefined && <span className="kb-took">{tookMs}ms</span>}
        </div>
        {subtitle && (
          <span className="kb-sub" title={subtitle}>
            {subtitle}
          </span>
        )}
      </div>
      <div className="kb-head-right">
        <span className={`kb-badge ${badgeTone}`}>{badgeText}</span>
        {showChevron && <span className="think-chevron">▸</span>}
      </div>
    </>
  );
}

function SearchResultsBody({
  results,
  degraded,
  showAll,
  onToggleAll,
  expandedIds,
  onToggleItem,
  t,
}: {
  results: KbCitationItem[];
  degraded: boolean;
  showAll: boolean;
  onToggleAll: () => void;
  expandedIds: Set<string>;
  onToggleItem: (id: string) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  const visible = showAll ? results : results.slice(0, DEFAULT_VISIBLE);
  const hiddenCount = results.length - visible.length;

  return (
    <>
      {degraded && <div className="kb-degraded">{t('kb.degradedHint')}</div>}
      <ol className="kb-list">
        {visible.map((item, idx) => {
          const itemKey = `${item.chunkId}_${idx}`;
          const expanded = expandedIds.has(itemKey);
          const pageLabel = formatPageLabel(t, item.pageStart, item.pageEnd);
          const canExpand = Boolean(
            item.text || item.dateBasis || item.supersededBy || item.newerVersion || item.duplicates.length,
          );

          const onCardClick = (e: MouseEvent<HTMLLIElement>) => {
            if (!canExpand) return;
            if ((e.target as HTMLElement).closest('a, button')) return;
            onToggleItem(itemKey);
          };

          return (
            <li
              key={itemKey}
              className={`kb-item${expanded ? ' expanded' : ''}${canExpand ? ' clickable' : ''}`}
              onClick={onCardClick}
            >
              <div className="kb-item-top">
                <span className="kb-rank">{String(idx + 1).padStart(2, '0')}</span>
                <span className="kb-doc-title" title={item.rawTitle ?? item.title}>
                  {item.title}
                </span>
                {item.docNo && <span className="kb-doc-no">{item.docNo}</span>}
              </div>

              <div className="kb-meta-row">
                {item.clauseLocation && (
                  <span className="kb-tag clause">{item.clauseLocation}</span>
                )}
                {item.publishDate && (
                  <span className="kb-tag date" title={item.dateBasis ?? undefined}>
                    <CalendarIcon />
                    <span>{item.publishDate}</span>
                  </span>
                )}
                {pageLabel && (
                  <span
                    className="kb-tag page"
                    title={item.pageCount ? t('kb.pageTotal', { count: item.pageCount }) : undefined}
                  >
                    {pageLabel}
                  </span>
                )}
                {item.docType && <span className="kb-tag type">{item.docType}</span>}
                {item.supersededBy && (
                  <span className="kb-tag warn" title={item.supersededBy}>
                    {t('kb.superseded')}
                  </span>
                )}
                {!item.supersededBy && item.newerVersion && (
                  <span className="kb-tag warn" title={item.newerVersion}>
                    {t('kb.newerVersion')}
                  </span>
                )}
                {item.isVersionReview && (
                  <span className="kb-tag review">{t('kb.versionReview')}</span>
                )}
                {item.duplicates.length > 0 && (
                  <span className="kb-tag" title={item.duplicates.join('、')}>
                    {t('kb.duplicates', { count: item.duplicates.length })}
                  </span>
                )}
              </div>

              {(item.fileName || item.sourceFile || item.fileUrl || item.sourceUrl) && (
                <div className="kb-file-row">
                  {(item.fileName || item.sourceFile) && (
                    <span className="kb-filename" title={item.sourceFile ?? item.fileName}>
                      <FileTextIcon />
                      <span className="kb-filename-text">{item.fileName ?? item.sourceFile}</span>
                    </span>
                  )}
                  {(item.fileUrl || item.sourceUrl) && (
                    <div className="kb-links">
                      {item.fileUrl && (
                        <a
                          className="kb-link"
                          href={item.fileUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <span>{t('kb.openFile')}</span>
                          <ExternalLinkIcon />
                        </a>
                      )}
                      {item.sourceUrl && (
                        <a
                          className="kb-link"
                          href={item.sourceUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <span>{t('kb.openSource')}</span>
                          <ExternalLinkIcon />
                        </a>
                      )}
                    </div>
                  )}
                </div>
              )}

              {canExpand && (
                <>
                  {expanded && (
                    <div className="kb-excerpt">
                      {item.text && <p className="kb-excerpt-text">{item.text}</p>}
                      {(item.dateBasis ||
                        item.supersededBy ||
                        item.newerVersion ||
                        item.duplicates.length > 0) && (
                        <div className="kb-excerpt-notes">
                          {item.dateBasis && <span>{item.dateBasis}</span>}
                          {item.supersededBy && <span>{item.supersededBy}</span>}
                          {item.newerVersion && <span>{item.newerVersion}</span>}
                          {item.duplicates.length > 0 && (
                            <span>{item.duplicates.join(' · ')}</span>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                  <button
                    type="button"
                    className="kb-excerpt-btn"
                    aria-expanded={expanded}
                    onClick={() => onToggleItem(itemKey)}
                  >
                    {expanded ? t('kb.hideExcerpt') : t('kb.viewExcerpt')}
                  </button>
                </>
              )}
            </li>
          );
        })}
      </ol>
      {results.length > DEFAULT_VISIBLE && (
        <button type="button" className="kb-more-btn" onClick={onToggleAll}>
          {showAll ? t('kb.showLess') : t('kb.showMore', { count: hiddenCount })}
        </button>
      )}
    </>
  );
}

function ChunksBody({
  data,
  showAll,
  onToggleAll,
  expandedIds,
  onToggleItem,
  t,
}: {
  data: NonNullable<ReturnType<typeof parseKbDocumentChunksResult>>;
  showAll: boolean;
  onToggleAll: () => void;
  expandedIds: Set<string>;
  onToggleItem: (id: string) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  const visible = showAll ? data.chunks : data.chunks.slice(0, DEFAULT_VISIBLE);
  const hiddenCount = data.chunks.length - visible.length;
  const firstIdx = data.chunks[0]?.index ?? data.offset ?? 0;
  const lastIdx = data.chunks[data.chunks.length - 1]?.index ?? firstIdx + data.chunks.length - 1;

  return (
    <>
      <div className="kb-doc-banner">
        <div className="kb-meta-row">
          {data.publishDate && (
            <span className="kb-tag date" title={data.dateBasis ?? undefined}>
              <CalendarIcon />
              <span>{data.publishDate}</span>
            </span>
          )}
          {data.pageCount && (
            <span className="kb-tag page">{t('kb.pageTotal', { count: data.pageCount })}</span>
          )}
          {data.totalChunks !== undefined && (
            <span className="kb-tag type">
              {t('kb.chunkRange', {
                start: firstIdx + 1,
                end: lastIdx + 1,
                total: data.totalChunks,
              })}
            </span>
          )}
          {data.supersededBy && <span className="kb-tag warn">{t('kb.superseded')}</span>}
          {!data.supersededBy && data.newerVersion && (
            <span className="kb-tag warn">{t('kb.newerVersion')}</span>
          )}
        </div>
        {(data.fileUrl || data.sourceUrl) && (
          <div className="kb-links">
            {data.fileUrl && (
              <a className="kb-link" href={data.fileUrl} target="_blank" rel="noopener noreferrer">
                <span>{t('kb.openFile')}</span>
                <ExternalLinkIcon />
              </a>
            )}
            {data.sourceUrl && (
              <a className="kb-link" href={data.sourceUrl} target="_blank" rel="noopener noreferrer">
                <span>{t('kb.openSource')}</span>
                <ExternalLinkIcon />
              </a>
            )}
          </div>
        )}
      </div>

      <ol className="kb-list">
        {visible.map((chunk: KbDocumentChunkItem, idx: number) => {
          const key = `${chunk.chunkId}_${idx}`;
          const expanded = expandedIds.has(key);
          const pageLabel = formatPageLabel(t, chunk.pageStart, chunk.pageEnd);
          const seqNum = chunk.index !== undefined ? chunk.index + 1 : idx + 1;
          const canExpand = Boolean(chunk.text);

          return (
            <li
              key={key}
              className={`kb-item${expanded ? ' expanded' : ''}${canExpand ? ' clickable' : ''}`}
              onClick={(e) => {
                if (!canExpand) return;
                if ((e.target as HTMLElement).closest('a, button')) return;
                onToggleItem(key);
              }}
            >
              <div className="kb-meta-row">
                <span className="kb-rank">{String(seqNum).padStart(2, '0')}</span>
                <span className="kb-tag type">{t('kb.chunkIndex', { index: seqNum })}</span>
                {chunk.clauseLocation && (
                  <span className="kb-tag clause">{chunk.clauseLocation}</span>
                )}
                {pageLabel && <span className="kb-tag page">{pageLabel}</span>}
                {chunk.isAnchor && <span className="kb-tag review">{t('kb.anchor')}</span>}
              </div>

              {canExpand && (
                <>
                  {expanded && (
                    <div className="kb-excerpt">
                      <p className="kb-excerpt-text">{chunk.text}</p>
                    </div>
                  )}
                  <button
                    type="button"
                    className="kb-excerpt-btn"
                    aria-expanded={expanded}
                    onClick={() => onToggleItem(key)}
                  >
                    {expanded ? t('kb.hideExcerpt') : t('kb.viewExcerpt')}
                  </button>
                </>
              )}
            </li>
          );
        })}
      </ol>

      {data.chunks.length > DEFAULT_VISIBLE && (
        <button type="button" className="kb-more-btn" onClick={onToggleAll}>
          {showAll ? t('kb.showLess') : t('kb.showMore', { count: hiddenCount })}
        </button>
      )}
    </>
  );
}

function DocumentsBody({
  documents,
  showAll,
  onToggleAll,
  t,
}: {
  documents: KbDocumentCatalogItem[];
  showAll: boolean;
  onToggleAll: () => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  const visible = showAll ? documents : documents.slice(0, DEFAULT_VISIBLE);
  const hiddenCount = documents.length - visible.length;

  return (
    <>
      <ol className="kb-list">
        {visible.map((doc, idx) => (
          <li key={doc.docId} className="kb-item">
            <div className="kb-item-top">
              <span className="kb-rank">{String(idx + 1).padStart(2, '0')}</span>
              <span className="kb-doc-title">{doc.title}</span>
              {doc.docNo && <span className="kb-doc-no">{doc.docNo}</span>}
            </div>
            <div className="kb-meta-row">
              {doc.publishDate && (
                <span className="kb-tag date" title={doc.dateBasis ?? undefined}>
                  <CalendarIcon />
                  <span>{doc.publishDate}</span>
                </span>
              )}
              {doc.docType && <span className="kb-tag type">{doc.docType}</span>}
              {doc.department && <span className="kb-tag">{doc.department}</span>}
              {doc.pages && (
                <span className="kb-tag page">{t('kb.pageTotal', { count: doc.pages })}</span>
              )}
            </div>
            {(doc.fileName || doc.sourceFile || doc.fileUrl || doc.sourceUrl) && (
              <div className="kb-file-row">
                {(doc.fileName || doc.sourceFile) && (
                  <span className="kb-filename" title={doc.sourceFile ?? doc.fileName}>
                    <FileTextIcon />
                    <span className="kb-filename-text">{doc.fileName ?? doc.sourceFile}</span>
                  </span>
                )}
                {(doc.fileUrl || doc.sourceUrl) && (
                  <div className="kb-links">
                    {doc.fileUrl && (
                      <a
                        className="kb-link"
                        href={doc.fileUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <span>{t('kb.openFile')}</span>
                        <ExternalLinkIcon />
                      </a>
                    )}
                    {doc.sourceUrl && (
                      <a
                        className="kb-link"
                        href={doc.sourceUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <span>{t('kb.openSource')}</span>
                        <ExternalLinkIcon />
                      </a>
                    )}
                  </div>
                )}
              </div>
            )}
          </li>
        ))}
      </ol>
      {documents.length > DEFAULT_VISIBLE && (
        <button type="button" className="kb-more-btn" onClick={onToggleAll}>
          {showAll ? t('kb.showLess') : t('kb.showMore', { count: hiddenCount })}
        </button>
      )}
    </>
  );
}
