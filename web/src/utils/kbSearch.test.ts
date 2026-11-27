import { describe, expect, it } from 'vitest';
import {
  cleanDisplayTitle,
  formatClauseLocation,
  getKbToolKind,
  parseKbDocumentChunksResult,
  parseKbDocumentsResult,
  parseKbInput,
  parseKbSearchResult,
  safeHttpUrl,
  splitSourceFile,
} from './kbSearch';

describe('getKbToolKind', () => {
  it('matches bare and namespaced KB retrieval tools only', () => {
    expect(getKbToolKind('kb_search')).toBe('search');
    expect(getKbToolKind('kb_document_chunks')).toBe('chunks');
    expect(getKbToolKind('kb_documents')).toBe('documents');
    expect(getKbToolKind('user__u1__kb_search')).toBe('search');
    expect(getKbToolKind('local__kb__kb_document_chunks')).toBe('chunks');
    expect(getKbToolKind('local__kb__kb_documents')).toBe('documents');

    expect(getKbToolKind('kb_meta')).toBeNull();
    expect(getKbToolKind('cuc_timetable')).toBeNull();
    expect(getKbToolKind('web_search')).toBeNull();
    expect(getKbToolKind('')).toBeNull();
  });
});

describe('string and url helpers', () => {
  it('validates http/https urls and rejects unsafe schemes', () => {
    expect(safeHttpUrl('https://kb.acgurl.cn/v1/files/abc#page=2')).toBe(
      'https://kb.acgurl.cn/v1/files/abc#page=2',
    );
    expect(safeHttpUrl('http://127.0.0.1:8000/v1/files/abc')).toBe(
      'http://127.0.0.1:8000/v1/files/abc',
    );
    expect(safeHttpUrl('javascript:alert(1)')).toBeUndefined();
    expect(safeHttpUrl('data:text/html,hi')).toBeUndefined();
    expect(safeHttpUrl('')).toBeUndefined();
  });

  it('splits source_file into fileName and collection', () => {
    expect(
      splitSourceFile('中传小资/16-中传资产字（2018）76号 中国传媒大学国有资产管理办法.pdf'),
    ).toEqual({
      fileName: '16-中传资产字（2018）76号 中国传媒大学国有资产管理办法.pdf',
      collection: '中传小资',
    });
    expect(splitSourceFile('plain.pdf')).toEqual({
      fileName: 'plain.pdf',
      collection: undefined,
    });
  });

  it('cleans noisy suffixes and duplicate leading doc_no from display title', () => {
    expect(
      cleanDisplayTitle(
        '中传资产字（2018）76号 中国传媒大学国有资产管理办法',
        '中传资产字（2018）76号',
        '16-中传资产字（2018）76号 中国传媒大学国有资产管理办法.pdf',
      ),
    ).toBe('中国传媒大学国有资产管理办法');
    expect(cleanDisplayTitle('AI中国传媒大学非学历教育项目办学指导快问快答.docx_view')).toBe(
      'AI中国传媒大学非学历教育项目办学指导快问快答',
    );
    expect(cleanDisplayTitle('中传发〔2024〕1号', '中传发〔2024〕1号')).toBe('中传发〔2024〕1号');
  });

  it('formats clause location without duplicating final section entry', () => {
    expect(formatClauseLocation('第二条', ['第一章'])).toBe('第一章 · 第二条');
    expect(formatClauseLocation('第二条', ['第一章', '第二条'])).toBe('第一章 · 第二条');
    expect(formatClauseLocation('第五条', [])).toBe('第五条');
    expect(formatClauseLocation(undefined, [])).toBeUndefined();
  });
});

describe('parseKbInput', () => {
  it('parses running Input payload with query and filters', () => {
    const parsed = parseKbInput(
      'Input: {"query": "宿舍床尺寸", "role": "本科生", "doc_type": ["制度"], "page": 3}',
    );
    expect(parsed).toEqual({
      query: '宿舍床尺寸',
      assistant: undefined,
      docType: ['制度'],
      role: '本科生',
      campus: undefined,
      docId: undefined,
      chunkId: undefined,
      page: 3,
      pageEnd: undefined,
    });
    expect(parseKbInput('not json')).toBeNull();
  });
});

describe('parseKbSearchResult', () => {
  it('parses authoritative citation metadata, file links, and duplicates', () => {
    const payload = JSON.stringify({
      query: '国有资产管理办法第二条',
      no_answer: false,
      answer_mode: 'direct',
      confidence: 0.94,
      took_ms: 42.6,
      results: [
        {
          doc_id: 'doc1',
          chunk_id: 'doc1-0001',
          text: '第二条 本办法适用于……',
          duplicates: [
            { doc_id: 'doc2', doc_title: '2026学生工作规章制度汇编', source_file: '汇编/2026.pdf' },
          ],
          citation: {
            doc_title: '中传资产字（2018）76号 中国传媒大学国有资产管理办法',
            doc_no: '中传资产字（2018）76号',
            doc_type: '制度',
            clause_no: '第二条',
            page_start: 2,
            page_end: 3,
            page_count: 14,
            section_path: ['第一章 总则'],
            source_file: '中传小资/16-中传资产字（2018）76号 中国传媒大学国有资产管理办法.pdf',
            source_url: 'https://aihub.cuc.edu.cn/doc.pdf',
            publish_date: '2018-04-09',
            date_basis: '文内日期',
            superseded_by: '中传资产字（2025）10号',
            file_url: 'https://kb.acgurl.cn/v1/files/doc1#page=2',
          },
        },
        {
          doc_id: 'doc3',
          chunk_id: 'doc3-0002',
          text: 'unsafe link test',
          citation: {
            doc_title: '测试文档.docx_view',
            file_url: 'javascript:alert(1)',
            source_url: 'data:text/plain,bad',
          },
        },
      ],
    });

    const parsed = parseKbSearchResult(payload);
    expect(parsed).not.toBeNull();
    expect(parsed?.answerMode).toBe('direct');
    expect(parsed?.tookMs).toBe(43);
    expect(parsed?.results).toHaveLength(2);
    expect(parsed?.results[0]).toMatchObject({
      docId: 'doc1',
      chunkId: 'doc1-0001',
      title: '中国传媒大学国有资产管理办法',
      docNo: '中传资产字（2018）76号',
      docType: '制度',
      clauseLocation: '第一章 总则 · 第二条',
      pageStart: 2,
      pageEnd: 3,
      pageCount: 14,
      publishDate: '2018-04-09',
      dateBasis: '文内日期',
      fileName: '16-中传资产字（2018）76号 中国传媒大学国有资产管理办法.pdf',
      collection: '中传小资',
      fileUrl: 'https://kb.acgurl.cn/v1/files/doc1#page=2',
      sourceUrl: 'https://aihub.cuc.edu.cn/doc.pdf',
      supersededBy: '中传资产字（2025）10号',
      duplicates: ['2026学生工作规章制度汇编'],
      isVersionReview: false,
    });
    expect(parsed?.results[1].title).toBe('测试文档');
    expect(parsed?.results[1].fileUrl).toBeUndefined();
    expect(parsed?.results[1].sourceUrl).toBeUndefined();
  });

  it('handles related, degraded, version_review, place_answer, and missing_version_year', () => {
    const related = parseKbSearchResult(
      JSON.stringify({
        query: '转专业',
        no_answer: true,
        answer_mode: 'related',
        degraded: true,
        version_review: ['d2-0001'],
        results: [
          {
            doc_id: 'd2',
            chunk_id: 'd2-0001',
            text: '新版规定...',
            citation: { doc_title: '2025转专业办法', newer_version: 'd3' },
          },
        ],
      }),
    );
    expect(related?.degraded).toBe(true);
    expect(related?.answerMode).toBe('related');
    expect(related?.results[0].isVersionReview).toBe(true);
    expect(related?.results[0].newerVersion).toBe('d3');

    const place = parseKbSearchResult(
      JSON.stringify({
        query: '图书馆在哪',
        no_answer: false,
        answer_mode: 'direct',
        place_answer: true,
        results: [],
        places: [{ name: '图书馆' }],
      }),
    );
    expect(place?.placeAnswer).toBe(true);
    expect(place?.results).toEqual([]);

    const missing = parseKbSearchResult(
      JSON.stringify({
        query: '2027年校历',
        no_answer: true,
        answer_mode: 'none',
        missing_version_year: '2027',
        results: [],
      }),
    );
    expect(missing?.answerMode).toBe('none');
    expect(missing?.missingVersionYear).toBe('2027');

    expect(parseKbSearchResult('not json')).toBeNull();
    expect(parseKbSearchResult('{"foo":"bar"}')).toBeNull();
  });
});

describe('parseKbDocumentChunksResult and parseKbDocumentsResult', () => {
  it('parses kb_document_chunks payload with anchor and filename', () => {
    const parsed = parseKbDocumentChunksResult(
      JSON.stringify({
        doc_id: 'd1',
        page_count: 10,
        total_chunks: 20,
        offset: 4,
        returned: 2,
        anchor_index: 5,
        anchor_chunk_id: 'd1-0005',
        publish_date: '2024-09-01',
        date_basis: '官网发布日期',
        file_url: 'https://kb.acgurl.cn/v1/files/d1',
        chunks: [
          {
            index: 4,
            chunk_id: 'd1-0004',
            clause_no: '第十条',
            section_path: ['第三章'],
            page_start: 4,
            page_end: 4,
            source_file: '教务处/本科生学籍管理规定.pdf',
            text: '第十条内容',
          },
          {
            index: 5,
            chunk_id: 'd1-0005',
            clause_no: '第十一条',
            section_path: ['第三章'],
            page_start: 5,
            page_end: 5,
            source_file: '教务处/本科生学籍管理规定.pdf',
            text: '第十一条内容',
          },
        ],
      }),
    );
    expect(parsed).toMatchObject({
      docId: 'd1',
      title: '本科生学籍管理规定',
      fileName: '本科生学籍管理规定.pdf',
      collection: '教务处',
      pageCount: 10,
      totalChunks: 20,
      publishDate: '2024-09-01',
    });
    expect(parsed?.chunks[0].isAnchor).toBe(false);
    expect(parsed?.chunks[1].isAnchor).toBe(true);
    expect(parsed?.chunks[1].clauseLocation).toBe('第三章 · 第十一条');
  });

  it('parses kb_documents catalog payload', () => {
    const parsed = parseKbDocumentsResult(
      JSON.stringify({
        count: 1,
        documents: [
          {
            doc_id: 'doc-9',
            doc_title: '中传教字（2025）12号 辅修管理办法',
            doc_no: '中传教字（2025）12号',
            doc_type: '制度',
            department: '教务处',
            pages: 8,
            publish_date: '2025-03-15',
            source_file: '教务处/辅修管理办法.pdf',
            file_url: 'https://kb.acgurl.cn/v1/files/doc-9',
            source_url: 'https://jwc.cuc.edu.cn/doc-9',
          },
        ],
      }),
    );
    expect(parsed?.count).toBe(1);
    expect(parsed?.documents[0]).toMatchObject({
      docId: 'doc-9',
      title: '辅修管理办法',
      docNo: '中传教字（2025）12号',
      department: '教务处',
      pages: 8,
      publishDate: '2025-03-15',
      fileName: '辅修管理办法.pdf',
    });
  });
});
