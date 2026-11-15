import { useCopied } from '../hooks/useCopied';
import { CheckIcon, CopyIcon } from './icons';

// 小号复制按钮：复制成功后图标换成对勾并短暂变主色
export function CopyButton({
  text,
  label,
  copiedLabel,
}: {
  text: string | null | undefined;
  label: string;
  copiedLabel: string;
}) {
  const { copied, copy } = useCopied();
  return (
    <button
      type="button"
      className={`mini-btn icon-only${copied ? ' copied' : ''}`}
      aria-label={copied ? copiedLabel : label}
      title={copied ? copiedLabel : label}
      disabled={!text}
      onClick={() => text && copy(text)}
    >
      {copied ? <CheckIcon /> : <CopyIcon />}
    </button>
  );
}
