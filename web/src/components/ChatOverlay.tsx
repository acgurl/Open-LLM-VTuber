import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useChat, type ChatEntry } from '../stores/chat';
import { MessageBubble } from './MessageBubble';
import { ToolCallCard } from './ToolCallCard';

const NEAR_BOTTOM_PX = 72;

export function ChatOverlay() {
  const { t } = useTranslation();
  const entries = useChat((s) => s.entries);
  const ref = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const jumping = useRef(false);
  const firstId = useRef<string | null>(null);
  const [showJump, setShowJump] = useState(false);
  const [unread, setUnread] = useState(false);

  // 用户停在底部时始终吸底；主动上翻后不再抢滚动位置，只提示有新内容
  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // 换会话（首条消息变化）时重新吸底，避免沿用上一段对话的上翻状态
    const first = entries[0]?.id ?? null;
    if (first !== firstId.current) {
      firstId.current = first;
      pinned.current = true;
      jumping.current = false;
      setShowJump(false);
      setUnread(false);
    }

    if (!pinned.current) {
      if (entries.length > 0) {
        setShowJump(true);
        setUnread(true);
      }
      return;
    }
    el.scrollTop = el.scrollHeight;
  }, [entries]);

  const onScroll = () => {
    const el = ref.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
    if (jumping.current) {
      if (!near) return;
      jumping.current = false;
    }
    pinned.current = near;
    setShowJump(!near && el.scrollHeight > el.clientHeight + 8);
    if (near) setUnread(false);
  };

  const jumpToLatest = () => {
    const el = ref.current;
    if (!el) return;
    jumping.current = true;
    pinned.current = true;
    setShowJump(false);
    setUnread(false);
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  };

  return (
    <div className="chat-shell">
      <div className="chat-overlay" ref={ref} onScroll={onScroll}>
        {entries.map((e: ChatEntry) =>
          e.kind === 'text' ? (
            <MessageBubble key={e.id} entry={e} />
          ) : (
            <ToolCallCard key={e.id} entry={e} />
          ),
        )}
      </div>
      {showJump && (
        <button
          className={`scroll-jump${unread ? ' unread' : ''}`}
          aria-label={t('chat.latest')}
          title={t('chat.latest')}
          onClick={jumpToLatest}
        >
          <ArrowDownIcon />
          <span>{t('chat.latest')}</span>
          {unread && <span className="scroll-jump-dot" />}
        </button>
      )}
    </div>
  );
}

function ArrowDownIcon() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 5v14" />
      <path d="m6 13 6 6 6-6" />
    </svg>
  );
}
