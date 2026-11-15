import { useTranslation } from 'react-i18next';
import { useModels } from '../stores/models';
import { setThinking } from '../services/actions';
import type { ThinkingLevel } from '../protocol/types';
import { BulbIcon } from './icons';

// 这些档位 id 表示“不思考”
const OFF_IDS = new Set(['off', 'none']);
export const isOffLevel = (id: string | null) => id === null || OFF_IDS.has(id);

// 当前模型的思考档位信息；模型没配档位（或用角色默认）时 available 为 false
export function useThinking() {
  const models = useModels((s) => s.models);
  const current = useModels((s) => s.current);
  const level = useModels((s) => s.thinking);
  const switching = useModels((s) => s.switching);
  const lastOn = useModels((s) => s.lastThinkingOn);
  const info = models.find((m) => m.id === current)?.thinking;
  const levels = info?.levels ?? [];
  const active =
    levels.find((l) => l.id === level) ?? levels.find((l) => l.id === info?.default) ?? levels[0] ?? null;
  const offLevel = levels.find((l) => isOffLevel(l.id)) ?? null;
  const onLevels = levels.filter((l) => !isOffLevel(l.id));
  return {
    available: levels.length > 1,
    modelId: current,
    active,
    on: active !== null && !isOffLevel(active.id),
    offLevel,
    onLevels,
    lastOn: current ? lastOn[current] : undefined,
    switching,
  };
}

// 加号菜单里的思考区：一行开关 + 开启后的强度分段。没有档位时不渲染。
export function ThinkingControls() {
  const { t } = useTranslation();
  const { available, active, on, offLevel, onLevels, lastOn, switching } = useThinking();
  if (!available || !active) return null;

  const label = (l: ThinkingLevel) => l.name || t(`thinking.level.${l.id}`, { defaultValue: l.id });
  // 没有“不思考”档的模型（只能在几档强度间选）不显示开关，只显示强度
  const canToggle = offLevel !== null && onLevels.length > 0;

  const toggle = () => {
    if (on) {
      if (offLevel) setThinking(offLevel.id);
      return;
    }
    // 打开时回到上次用过的强度，没有就用最轻的一档
    const target = onLevels.find((l) => l.id === lastOn) ?? onLevels[0];
    if (target) setThinking(target.id);
  };

  return (
    <div className={`thinking-section${on ? ' on' : ''}`}>
      {canToggle && (
        <button
          type="button"
          role="switch"
          aria-checked={on}
          className="thinking-row"
          disabled={switching}
          onClick={toggle}
        >
          <span className="thinking-row-icon">
            <BulbIcon lit={on} />
          </span>
          <span className="thinking-row-text">
            <span className="thinking-row-title">{t('thinking.label')}</span>
            <span className="thinking-row-desc">{on ? t('thinking.descOn') : t('thinking.descOff')}</span>
          </span>
          <span className="thinking-switch" aria-hidden="true">
            <i />
          </span>
        </button>
      )}
      {(on || !canToggle) && onLevels.length > 1 && (
        <div className="thinking-levels" role="radiogroup" aria-label={t('thinking.title')}>
          {onLevels.map((l) => {
            const selected = l.id === active.id;
            return (
              <button
                key={l.id}
                type="button"
                role="radio"
                aria-checked={selected}
                className={`thinking-level${selected ? ' selected' : ''}`}
                disabled={switching}
                onClick={() => setThinking(l.id)}
              >
                {label(l)}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
