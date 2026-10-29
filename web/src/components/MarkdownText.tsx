import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

// 模型输出的链接一律新标签页打开，避免整页被打断。
const markdownComponents: Components = {
  p: 'span',
  a: ({ children, href, title }) => (
    <a href={href} title={title} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
};

// markdown 解析链（react-markdown + remark-gfm + micromark，约 160KB）与首屏无关，
// 由 MessageBubble 懒加载，等第一条回答出现时才拉取。
export default function MarkdownText({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
      {text}
    </ReactMarkdown>
  );
}
