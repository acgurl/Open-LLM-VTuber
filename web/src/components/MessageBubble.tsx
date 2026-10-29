import { memo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useConnection } from '../stores/connection';
import { buildTagSet, splitByTags, splitThink, stripTags } from '../utils/text';
import type { ChatTextEntry } from '../stores/chat';
import { ThinkBlock } from './ThinkBlock';

// 模型输出的链接一律新标签页打开，避免整页被打断。
const markdownComponents: Components = {
  p: 'span',
  a: ({ children, href, title }) => (
    <a href={href} title={title} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
};

// AI 气泡：流式增量合并进同一个气泡；[tag] 渲染为动作块；<think> 折叠。
// memo 让流式增量只重渲染正在长的那一条，历史气泡不再每帧重新解析 markdown
export const MessageBubble = memo(function MessageBubble({ entry }: { entry: ChatTextEntry }) {
  const { t, i18n } = useTranslation();
  const modelInfo = useConnection((s) => s.modelInfo);
  const [copied, setCopied] = useState(false);
  const tagSet = buildTagSet(modelInfo);
  const isAi = entry.role === 'ai';

  const copyText = () => {
    const visible = splitThink(entry.text)
      .filter((b) => b.kind === 'normal')
      .map((b) => b.text)
      .join('');
    const clean = stripTags(visible, tagSet);
    if (!clean || !navigator.clipboard) return;
    void navigator.clipboard.writeText(clean).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1400);
      },
      () => setCopied(false),
    );
  };

  return (
    <div className={`bubble-row ${isAi ? 'ai' : 'human'}`}>
      <div className="bubble-stack">
        <div className={`bubble ${entry.streaming ? 'streaming' : ''}`}>
          {isAi ? (
            <AiText text={entry.text} tagSet={tagSet} streaming={Boolean(entry.streaming)} />
          ) : (
            <PlainText text={entry.text} />
          )}
        </div>
        <div className="bubble-meta">
          <time dateTime={new Date(entry.ts).toISOString()}>
            {new Date(entry.ts).toLocaleTimeString(i18n.language, {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </time>
          <button
            className={`bubble-copy${copied ? ' copied' : ''}`}
            aria-label={copied ? t('chat.copied') : t('chat.copy')}
            title={copied ? t('chat.copied') : t('chat.copy')}
            onClick={copyText}
          >
            {copied ? <CheckIcon /> : <CopyIcon />}
          </button>
        </div>
      </div>
    </div>
  );
});

function PlainText({ text }: { text: string }) {
  return <div className="bubble-text plain">{text}</div>;
}

function AiText({
  text,
  tagSet,
  streaming,
}: {
  text: string;
  tagSet: Set<string>;
  streaming: boolean;
}) {
  const blocks = splitThink(text);
  // 光标跟最后一段可见文本走，否则会作为块级兄弟掉到下一行
  const lastNormal = blocks.reduce((acc, b, i) => (b.kind === 'normal' ? i : acc), -1);
  return (
    <>
      {blocks.map((b, i) =>
        b.kind === 'think' ? (
          <ThinkBlock key={i} text={b.text} active={streaming && b.closed === false} />
        ) : (
          <TaggedMarkdown
            key={i}
            text={b.text}
            tagSet={tagSet}
            caret={streaming && i === lastNormal}
          />
        ),
      )}
    </>
  );
}

function TaggedMarkdown({
  text,
  tagSet,
  caret,
}: {
  text: string;
  tagSet: Set<string>;
  caret?: boolean;
}) {
  const tokens = splitByTags(text, tagSet);
  return (
    <div className="bubble-text">
      {tokens.map((tok, i) =>
        tok.kind === 'tag' ? (
          <span key={i} className="action-tag">
            {tok.value}
          </span>
        ) : (
          <ReactMarkdown key={i} remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {tok.value}
          </ReactMarkdown>
        ),
      )}
      {caret && <span className="caret" />}
    </div>
  );
}

function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="m5 12 4 4L19 6" />
    </svg>
  );
}
