import { useEffect, useRef } from 'react';
import { useChat, type ChatEntry } from '../stores/chat';
import { MessageBubble } from './MessageBubble';
import { ToolCallCard } from './ToolCallCard';

export function ChatOverlay() {
  const entries = useChat((s) => s.entries);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries]);

  return (
    <div className="chat-overlay" ref={ref}>
      {entries.map((e: ChatEntry) =>
        e.kind === 'text' ? (
          <MessageBubble key={e.id} entry={e} />
        ) : (
          <ToolCallCard key={e.id} entry={e} />
        ),
      )}
    </div>
  );
}
