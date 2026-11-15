import { lazy, memo, Suspense, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useConnection } from "../stores/connection";
import { buildTagSet, splitByTags, splitThink, stripTags } from "../utils/text";
import type { ChatTextEntry } from "../stores/chat";
import { ThinkBlock } from "./ThinkBlock";
import { useCopied } from "../hooks/useCopied";
import { CopyIcon, CheckIcon } from "./icons";

const MarkdownText = lazy(() => import("./MarkdownText"));

// AI 气泡：流式增量合并进同一个气泡；[tag] 渲染为动作块；<think> 拆成独立的思考卡。
// memo 让流式增量只重渲染正在长的那一条，历史气泡不再每帧重新解析 markdown
export const MessageBubble = memo(function MessageBubble({
  entry,
}: {
  entry: ChatTextEntry;
}) {
  const { t, i18n } = useTranslation();
  const modelInfo = useConnection((s) => s.modelInfo);
  const { copied, copy } = useCopied();
  const tagSet = useMemo(() => buildTagSet(modelInfo), [modelInfo]);
  const isAi = entry.role === "ai";

  const copyText = () => {
    const visible = splitThink(entry.text)
      .filter((b) => b.kind === "normal")
      .map((b) => b.text)
      .join("");
    const clean = stripTags(visible, tagSet);
    if (clean) copy(clean);
  };

  const meta = (
    <div className="bubble-meta">
      <time dateTime={new Date(entry.ts).toISOString()}>
        {new Date(entry.ts).toLocaleTimeString(i18n.language, {
          hour: "2-digit",
          minute: "2-digit",
        })}
      </time>
      <button
        className={`bubble-copy${copied ? " copied" : ""}`}
        aria-label={copied ? t("chat.copied") : t("chat.copy")}
        title={copied ? t("chat.copied") : t("chat.copy")}
        onClick={copyText}
      >
        {copied ? <CheckIcon /> : <CopyIcon />}
      </button>
    </div>
  );

  if (!isAi) {
    return (
      <div className="bubble-row human">
        <div className="bubble-stack">
          <div className="bubble">
            <PlainText text={entry.text} />
          </div>
          {meta}
        </div>
      </div>
    );
  }

  // 思考段是和工具卡同级的独立卡片，正文段才进气泡；连续正文合进同一个气泡
  const streaming = Boolean(entry.streaming);
  const blocks = splitThink(entry.text);
  const groups: (
    | { kind: "think"; text: string; active: boolean }
    | { kind: "text"; text: string }
  )[] = [];
  for (const b of blocks) {
    if (b.kind === "think") {
      groups.push({
        kind: "think",
        text: b.text,
        active: streaming && b.closed === false,
      });
    } else if (
      b.text.trim() ||
      groups.length === 0 ||
      groups[groups.length - 1].kind === "text"
    ) {
      const last = groups[groups.length - 1];
      if (last?.kind === "text") last.text += b.text;
      else groups.push({ kind: "text", text: b.text });
    }
  }
  const lastText = groups.reduce(
    (acc, g, i) => (g.kind === "text" && g.text.trim() ? i : acc),
    -1,
  );

  return (
    <>
      {groups.map((g, i) =>
        g.kind === "think" ? (
          <ThinkBlock key={i} text={g.text} active={g.active} />
        ) : g.text.trim() ? (
          <div key={i} className="bubble-row ai">
            <div className="bubble-stack">
              <div
                className={`bubble ${streaming && i === lastText ? "streaming" : ""}`}
              >
                <TaggedMarkdown
                  text={g.text}
                  tagSet={tagSet}
                  caret={streaming && i === lastText}
                />
              </div>
              {i === lastText && !streaming && meta}
            </div>
          </div>
        ) : null,
      )}
    </>
  );
});

function PlainText({ text }: { text: string }) {
  return <div className="bubble-text plain">{text}</div>;
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
        tok.kind === "tag" ? (
          <span key={i} className="action-tag">
            {tok.value}
          </span>
        ) : (
          <LazyMarkdown key={i} text={tok.value} />
        ),
      )}
      {caret && <span className="caret" />}
    </div>
  );
}

function LazyMarkdown({ text }: { text: string }) {
  return (
    <Suspense fallback={<span className="md-pending">{text}</span>}>
      <MarkdownText text={text} />
    </Suspense>
  );
}
