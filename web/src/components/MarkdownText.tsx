import { isValidElement, useRef, useState, type ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useTranslation } from 'react-i18next';

// 模型输出的链接一律新标签页打开，避免整页被打断。
const markdownComponents: Components = {
  p: 'span',
  a: ({ children, href, title }) => (
    <a href={href} title={title} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
  pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
};

// 代码块顶上挂一条语言标签 + 复制按钮；语言取自 ```lang 生成的 language-* 类名
function CodeBlock({ children }: { children?: ReactNode }) {
  const { t } = useTranslation();
  const preRef = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);
  const className = isValidElement<{ className?: string }>(children)
    ? (children.props.className ?? '')
    : '';
  const lang = /language-([\w+#-]+)/.exec(className)?.[1] ?? 'text';

  const copy = () => {
    const text = preRef.current?.textContent ?? '';
    if (!text || !navigator.clipboard) return;
    void navigator.clipboard.writeText(text.replace(/\n$/, '')).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1400);
      },
      () => setCopied(false),
    );
  };

  return (
    <div className="code-block">
      <div className="code-head">
        <span className="code-lang">{lang}</span>
        <button
          type="button"
          className={`code-copy${copied ? ' copied' : ''}`}
          aria-label={copied ? t('chat.copied') : t('chat.copyCode')}
          onClick={copy}
        >
          {copied ? t('chat.copied') : t('chat.copyCode')}
        </button>
      </div>
      <pre ref={preRef}>{children}</pre>
    </div>
  );
}

// markdown 解析链（react-markdown + remark-gfm + micromark，约 160KB）与首屏无关，
// 由 MessageBubble 懒加载，等第一条回答出现时才拉取。
export default function MarkdownText({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
      {text}
    </ReactMarkdown>
  );
}
