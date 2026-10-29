import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useChat, type ChatEntry } from '../stores/chat';
import { useConnection } from '../stores/connection';
import { MessageBubble } from './MessageBubble';
import { ToolCallCard } from './ToolCallCard';

const NEAR_BOTTOM_PX = 72;

export function ChatOverlay() {
  const { t } = useTranslation();
  const entries = useChat((s) => s.entries);
  const busy = useConnection((s) => s.busy);
  const ref = useRef<HTMLDivElement>(null);
  const stackRef = useRef<HTMLDivElement>(null);
  const frame = useRef(0);
  const pinned = useRef(true);
  const jumping = useRef(false);
  const firstId = useRef<string | null>(null);
  const [showJump, setShowJump] = useState(false);
  const [unread, setUnread] = useState(false);
  const [fade, setFade] = useState({ top: false, bottom: false });

  // 刚发出去、还没有任何回答片段时显示输入气泡；一旦有文本或工具卡就收起
  const last = entries[entries.length - 1];
  const awaiting = busy && last?.kind === 'text' && last.role === 'human';

  // 只有真的还有内容在视区外时才淡出边缘，否则短会话的首尾会被雾化
  const syncFade = (el: HTMLDivElement) => {
    const top = el.scrollTop > 4;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight > 4;
    setFade((prev) => (prev.top === top && prev.bottom === bottom ? prev : { top, bottom }));
  };

  // 吸底和边缘雾化都要读布局，合并成一帧一次：流式高频更新时不会连着触发 reflow
  const queueSync = () => {
    if (frame.current) return;
    frame.current = window.requestAnimationFrame(() => {
      frame.current = 0;
      const el = ref.current;
      if (!el) return;
      if (pinned.current) el.scrollTop = el.scrollHeight;
      syncFade(el);
    });
  };

  useEffect(() => () => window.cancelAnimationFrame(frame.current), []);

  // 用户停在底部时始终吸底；主动上翻后不再抢滚动位置，只提示有新内容
  useEffect(() => {
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
    }
    queueSync();
  }, [entries]);

  // 内容高度变化（气泡长高、工具卡折叠）时补吸底，否则上一条的阅读位置会被新高度打乱
  useEffect(() => {
    const el = ref.current;
    const stack = stackRef.current;
    if (!el || !stack || typeof ResizeObserver === 'undefined') return;
    // 观察的是内容而不是滚动容器：滚动容器自身高度不变，等不到折叠这种内部变化
    const ro = new ResizeObserver(() => {
      if (pinned.current) el.scrollTop = el.scrollHeight;
      syncFade(el);
    });
    ro.observe(stack);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 输入气泡出现/消失不经过 entries，需要单独补一次吸底
  useEffect(() => {
    queueSync();
  }, [awaiting]);

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
    syncFade(el);
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
    <div
      className={`chat-shell${fade.top ? ' fade-top' : ''}${fade.bottom ? ' fade-bottom' : ''}`}
    >
      <div className="chat-overlay" ref={ref} onScroll={onScroll}>
        <div className="chat-stack" ref={stackRef}>
          {entries.map((e: ChatEntry) =>
            e.kind === 'text' ? (
              <MessageBubble key={e.id} entry={e} />
            ) : (
              <ToolCallCard key={e.id} entry={e} />
            ),
          )}
          {awaiting && (
            <div className="bubble-row ai typing-row" aria-hidden="true">
              <div className="bubble-stack">
                <div className="bubble typing-bubble">
                  <span className="typing-dots">
                    <i />
                    <i />
                    <i />
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
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
