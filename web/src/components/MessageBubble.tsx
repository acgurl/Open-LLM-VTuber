import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useConnection } from '../stores/connection';
import { buildTagSet, splitByTags, splitThink, avatarUrl } from '../utils/text';
import type { ChatTextEntry } from '../stores/chat';
import { ThinkBlock } from './ThinkBlock';

// AI 气泡：流式增量合并进同一个气泡；[tag] 渲染为动作块；<think> 折叠。
export function MessageBubble({ entry }: { entry: ChatTextEntry }) {
  const modelInfo = useConnection((s) => s.modelInfo);
  const tagSet = buildTagSet(modelInfo);
  const isAi = entry.role === 'ai';
  const avatar = avatarUrl(entry.avatar);

  return (
    <div className={`bubble-row ${isAi ? 'ai' : 'human'}`}>
      <div className="bubble-avatar">
        {avatar ? (
          <img src={avatar} alt="" />
        ) : (
          <span>{(entry.name ?? (isAi ? 'A' : 'U')).slice(0, 1).toUpperCase()}</span>
        )}
      </div>
      <div className={`bubble ${entry.streaming ? 'streaming' : ''}`}>
        {isAi ? <AiText text={entry.text} tagSet={tagSet} /> : <PlainText text={entry.text} />}
        {entry.streaming && <span className="caret" />}
      </div>
    </div>
  );
}

function PlainText({ text }: { text: string }) {
  return <div className="bubble-text plain">{text}</div>;
}

function AiText({ text, tagSet }: { text: string; tagSet: Set<string> }) {
  const blocks = splitThink(text);
  return (
    <>
      {blocks.map((b, i) =>
        b.kind === 'think' ? (
          <ThinkBlock key={i} text={b.text} />
        ) : (
          <TaggedMarkdown key={i} text={b.text} tagSet={tagSet} />
        ),
      )}
    </>
  );
}

function TaggedMarkdown({ text, tagSet }: { text: string; tagSet: Set<string> }) {
  const tokens = splitByTags(text, tagSet);
  return (
    <div className="bubble-text">
      {tokens.map((tok, i) =>
        tok.kind === 'tag' ? (
          <span key={i} className="action-tag">
            {tok.value}
          </span>
        ) : (
          <ReactMarkdown key={i} remarkPlugins={[remarkGfm]} components={{ p: 'span' }}>
            {tok.value}
          </ReactMarkdown>
        ),
      )}
    </div>
  );
}
