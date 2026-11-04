import { useCallback, useEffect, useRef, useState } from 'react';

const COPIED_MS = 1400;

// 复制按钮的反馈状态：写剪贴板成功后 copied 亮 1.4s；卸载时清掉定时器。
// 空文本由调用方自己拦（各处判空的时机不同）
export function useCopied() {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const copy = useCallback((text: string) => {
    if (!navigator.clipboard) return;
    void navigator.clipboard.writeText(text).then(
      () => {
        setCopied(true);
        window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => setCopied(false), COPIED_MS);
      },
      () => setCopied(false),
    );
  }, []);

  return { copied, copy };
}
