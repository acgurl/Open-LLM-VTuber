export type KbToolKind = 'search' | 'chunks' | 'documents';

export interface KbToolInput {
  query?: string;
  assistant?: string;
  docType?: string[];
  role?: string;
  campus?: string;
  docId?: string;
  chunkId?: string;
  page?: number;
  pageEnd?: number;
}

export interface KbCitationItem {
  docId: string;
  chunkId: string;
  title: string;
  rawTitle?: string;
  docNo?: string;
  docType?: string;
  clauseNo?: string;
  sectionPath: string[];
  clauseLocation?: string;
  pageStart?: number;
  pageEnd?: number;
  pageCount?: number;
  publishDate?: string;
  dateBasis?: string;
  sourceFile?: string;
  fileName?: string;
  collection?: string;
  fileUrl?: string;
  sourceUrl?: string;
  supersededBy?: string;
  newerVersion?: string;
  duplicates: string[];
  text: string;
  isVersionReview: boolean;
}

export interface KbSearchResult {
  query?: string;
  answerMode: 'direct' | 'related' | 'none';
  noAnswer: boolean;
  confidence?: number;
  tookMs?: number;
  placeAnswer: boolean;
  degraded: boolean;
  missingVersionYear?: string;
  results: KbCitationItem[];
}

export interface KbDocumentChunkItem {
  index?: number;
  chunkId: string;
  clauseNo?: string;
  sectionPath: string[];
  clauseLocation?: string;
  pageStart?: number;
  pageEnd?: number;
  fileName?: string;
  text: string;
  isAnchor: boolean;
}

export interface KbDocumentChunksResult {
  docId: string;
  title: string;
  fileName?: string;
  collection?: string;
  pageCount?: number;
  fileUrl?: string;
  sourceUrl?: string;
  publishDate?: string;
  dateBasis?: string;
  supersededBy?: string;
  newerVersion?: string;
  totalChunks?: number;
  offset?: number;
  returned?: number;
  anchorIndex?: number;
  anchorChunkId?: string;
  pageRange?: [number, number];
  chunks: KbDocumentChunkItem[];
}

export interface KbDocumentCatalogItem {
  docId: string;
  title: string;
  docNo?: string;
  docType?: string;
  department?: string;
  publishDate?: string;
  dateBasis?: string;
  pages?: number;
  chunks?: number;
  sourceFile?: string;
  fileName?: string;
  fileUrl?: string;
  sourceUrl?: string;
}

export interface KbDocumentsResult {
  count: number;
  documents: KbDocumentCatalogItem[];
}

const KB_TOOL_KINDS: Record<string, KbToolKind> = {
  kb_search: 'search',
  kb_document_chunks: 'chunks',
  kb_documents: 'documents',
};

export function getKbToolKind(toolName: string): KbToolKind | null {
  const trimmed = toolName.trim();
  if (!trimmed) return null;
  if (KB_TOOL_KINDS[trimmed]) return KB_TOOL_KINDS[trimmed];
  for (const [suffix, kind] of Object.entries(KB_TOOL_KINDS)) {
    if (trimmed.endsWith(`__${suffix}`)) return kind;
  }
  return null;
}

const str = (v: unknown): string | undefined =>
  typeof v === 'string' && v.trim() !== '' ? v.trim() : undefined;

const posInt = (v: unknown): number | undefined =>
  typeof v === 'number' && Number.isInteger(v) && v > 0 ? v : undefined;

const nonNegInt = (v: unknown): number | undefined =>
  typeof v === 'number' && Number.isInteger(v) && v >= 0 ? v : undefined;

const strArray = (v: unknown): string[] => {
  if (!Array.isArray(v)) return [];
  return v.map((item) => (typeof item === 'string' ? item.trim() : '')).filter(Boolean);
};

const isRecord = (v: unknown): v is Record<string, unknown> =>
  Boolean(v) && typeof v === 'object' && !Array.isArray(v);

function tryParseRecord(content: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(content);
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function safeHttpUrl(v: unknown): string | undefined {
  const s = str(v);
  if (!s) return undefined;
  return /^https?:\/\//i.test(s) ? s : undefined;
}

export function splitSourceFile(sourceFile?: string): { fileName?: string; collection?: string } {
  const raw = str(sourceFile);
  if (!raw) return {};
  const parts = raw.split(/[\\/]+/).filter(Boolean);
  if (parts.length === 0) return {};
  const fileName = parts[parts.length - 1];
  const collection = parts.length > 1 ? parts.slice(0, -1).join('/') : undefined;
  return { fileName, collection };
}

export function cleanDisplayTitle(docTitle?: string, docNo?: string, fileName?: string): string {
  const rawBase = str(docTitle) ?? str(fileName) ?? '';
  let title = rawBase.replace(/(?:\.docx_view|\.pdf|\.docx|\.doc)+$/i, '').trim();
  const cleanDocNo = str(docNo);
  if (cleanDocNo && title.startsWith(cleanDocNo)) {
    const stripped = title.slice(cleanDocNo.length).trim();
    if (stripped) title = stripped;
  }
  return title || rawBase;
}

export function formatClauseLocation(clauseNo?: string, sectionPath?: string[]): string | undefined {
  const parts: string[] = [];
  for (const item of sectionPath ?? []) {
    const clean = item.trim();
    if (clean && parts[parts.length - 1] !== clean) parts.push(clean);
  }
  const cleanClause = str(clauseNo);
  if (cleanClause && parts[parts.length - 1] !== cleanClause) {
    parts.push(cleanClause);
  }
  return parts.length > 0 ? parts.join(' · ') : undefined;
}

export function parseKbInput(content: string): KbToolInput | null {
  const trimmed = content.trim();
  if (!trimmed) return null;
  const jsonText = trimmed.startsWith('Input:') ? trimmed.slice(6).trim() : trimmed;
  const data = tryParseRecord(jsonText);
  if (!data) return null;
  const docType = Array.isArray(data.doc_type)
    ? strArray(data.doc_type)
    : str(data.doc_type)
      ? [str(data.doc_type) as string]
      : undefined;
  return {
    query: str(data.query),
    assistant: str(data.assistant),
    docType: docType && docType.length > 0 ? docType : undefined,
    role: str(data.role),
    campus: str(data.campus),
    docId: str(data.doc_id),
    chunkId: str(data.chunk_id),
    page: posInt(data.page),
    pageEnd: posInt(data.page_end),
  };
}

function normalizeDuplicates(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const out: string[] = [];
  for (const item of raw) {
    if (typeof item === 'string') {
      const s = item.trim();
      if (s) out.push(s);
      continue;
    }
    if (isRecord(item)) {
      const { fileName } = splitSourceFile(str(item.source_file));
      const label = str(item.doc_title) ?? fileName ?? str(item.doc_id);
      if (label) out.push(label);
    }
  }
  return out;
}

export function parseKbSearchResult(content: string): KbSearchResult | null {
  const data = tryParseRecord(content);
  if (!data) return null;
  if (!Array.isArray(data.results) && typeof data.answer_mode !== 'string') {
    return null;
  }

  const rawMode = str(data.answer_mode);
  const answerMode: KbSearchResult['answerMode'] =
    rawMode === 'direct' || rawMode === 'related' || rawMode === 'none'
      ? rawMode
      : data.no_answer
        ? 'none'
        : 'direct';

  const reviewSet = new Set(strArray(data.version_review));
  const rawResults = Array.isArray(data.results) ? data.results : [];
  const results: KbCitationItem[] = [];

  for (let i = 0; i < rawResults.length; i += 1) {
    const row = rawResults[i];
    if (!isRecord(row)) continue;
    const citation = isRecord(row.citation) ? row.citation : {};
    const docId = str(row.doc_id) ?? `doc_${i}`;
    const chunkId = str(row.chunk_id) ?? `${docId}_${i}`;
    const rawTitle = str(citation.doc_title);
    const docNo = str(citation.doc_no);
    const sourceFile = str(citation.source_file);
    const { fileName, collection } = splitSourceFile(sourceFile);
    const sectionPath = strArray(citation.section_path);
    const clauseNo = str(citation.clause_no);

    results.push({
      docId,
      chunkId,
      title: cleanDisplayTitle(rawTitle, docNo, fileName) || docId,
      rawTitle,
      docNo,
      docType: str(citation.doc_type),
      clauseNo,
      sectionPath,
      clauseLocation: formatClauseLocation(clauseNo, sectionPath),
      pageStart: posInt(citation.page_start),
      pageEnd: posInt(citation.page_end),
      pageCount: posInt(citation.page_count),
      publishDate: str(citation.publish_date),
      dateBasis: str(citation.date_basis),
      sourceFile,
      fileName,
      collection,
      fileUrl: safeHttpUrl(citation.file_url),
      sourceUrl: safeHttpUrl(citation.source_url),
      supersededBy: str(citation.superseded_by),
      newerVersion: str(citation.newer_version),
      duplicates: normalizeDuplicates(row.duplicates),
      text: typeof row.text === 'string' ? row.text.trim() : '',
      isVersionReview: reviewSet.has(chunkId),
    });
  }

  return {
    query: str(data.query),
    answerMode,
    noAnswer: Boolean(data.no_answer),
    confidence: typeof data.confidence === 'number' && Number.isFinite(data.confidence)
      ? data.confidence
      : undefined,
    tookMs: typeof data.took_ms === 'number' && Number.isFinite(data.took_ms)
      ? Math.round(data.took_ms)
      : undefined,
    placeAnswer: Boolean(data.place_answer),
    degraded: Boolean(data.degraded),
    missingVersionYear: str(data.missing_version_year),
    results,
  };
}

export function parseKbDocumentChunksResult(content: string): KbDocumentChunksResult | null {
  const data = tryParseRecord(content);
  if (!data) return null;
  const docId = str(data.doc_id);
  if (!docId || !Array.isArray(data.chunks)) return null;

  const anchorChunkId = str(data.anchor_chunk_id);
  const anchorIndex = nonNegInt(data.anchor_index);
  let firstSourceFile: string | undefined;

  const chunks: KbDocumentChunkItem[] = [];
  for (let i = 0; i < data.chunks.length; i += 1) {
    const row = data.chunks[i];
    if (!isRecord(row)) continue;
    const sourceFile = str(row.source_file);
    if (!firstSourceFile && sourceFile) firstSourceFile = sourceFile;
    const { fileName } = splitSourceFile(sourceFile);
    const chunkId = str(row.chunk_id) ?? `${docId}_${i}`;
    const index = nonNegInt(row.index);
    const clauseNo = str(row.clause_no);
    const sectionPath = strArray(row.section_path);
    const isAnchor =
      (anchorChunkId !== undefined && chunkId === anchorChunkId) ||
      (anchorIndex !== undefined && index === anchorIndex);

    chunks.push({
      index,
      chunkId,
      clauseNo,
      sectionPath,
      clauseLocation: formatClauseLocation(clauseNo, sectionPath),
      pageStart: posInt(row.page_start),
      pageEnd: posInt(row.page_end),
      fileName,
      text: typeof row.text === 'string' ? row.text.trim() : '',
      isAnchor,
    });
  }

  const { fileName, collection } = splitSourceFile(firstSourceFile);
  const rawPageRange = Array.isArray(data.page_range) ? data.page_range : null;
  const pageRange: [number, number] | undefined =
    rawPageRange &&
    rawPageRange.length >= 2 &&
    posInt(rawPageRange[0]) !== undefined &&
    posInt(rawPageRange[1]) !== undefined
      ? [rawPageRange[0] as number, rawPageRange[1] as number]
      : undefined;

  return {
    docId,
    title: cleanDisplayTitle(undefined, undefined, fileName) || docId,
    fileName,
    collection,
    pageCount: posInt(data.page_count),
    fileUrl: safeHttpUrl(data.file_url),
    sourceUrl: safeHttpUrl(data.source_url),
    publishDate: str(data.publish_date),
    dateBasis: str(data.date_basis),
    supersededBy: str(data.superseded_by),
    newerVersion: str(data.newer_version),
    totalChunks: nonNegInt(data.total_chunks),
    offset: nonNegInt(data.offset),
    returned: nonNegInt(data.returned),
    anchorIndex,
    anchorChunkId,
    pageRange,
    chunks,
  };
}

export function parseKbDocumentsResult(content: string): KbDocumentsResult | null {
  const data = tryParseRecord(content);
  if (!data || !Array.isArray(data.documents)) return null;

  const documents: KbDocumentCatalogItem[] = [];
  for (let i = 0; i < data.documents.length; i += 1) {
    const row = data.documents[i];
    if (!isRecord(row)) continue;
    const docId = str(row.doc_id) ?? `doc_${i}`;
    const docNo = str(row.doc_no);
    const sourceFile = str(row.source_file);
    const { fileName } = splitSourceFile(sourceFile);
    const rawTitle = str(row.doc_title);

    documents.push({
      docId,
      title: cleanDisplayTitle(rawTitle, docNo, fileName) || docId,
      docNo,
      docType: str(row.doc_type),
      department: str(row.department),
      publishDate: str(row.publish_date),
      dateBasis: str(row.date_basis),
      pages: posInt(row.pages),
      chunks: nonNegInt(row.chunks),
      sourceFile,
      fileName,
      fileUrl: safeHttpUrl(row.file_url),
      sourceUrl: safeHttpUrl(row.source_url),
    });
  }

  return {
    count: nonNegInt(data.count) ?? documents.length,
    documents,
  };
}
