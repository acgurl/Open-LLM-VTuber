import { useTranslation } from 'react-i18next';
import { fetchConfigs, switchConfig } from '../services/actions';
import { useConnection } from '../stores/connection';
import { useSettings } from '../stores/settings';
import { useModels } from '../stores/models';
import { TopBarPicker } from './TopBarPicker';

const DOT_CLASS: Record<string, string> = {
  online: 'dot online',
  connecting: 'dot pending',
  reconnecting: 'dot pending',
  boot: 'dot pending',
  unauthorized: 'dot error',
  failed: 'dot error',
};

export function CharacterPicker() {
  const { t } = useTranslation();
  const status = useConnection((s) => s.status);
  const confName = useConnection((s) => s.confName);
  const statusText = useConnection((s) => s.statusText);
  const busy = useConnection((s) => s.busy);
  const configs = useSettings((s) => s.configs);
  const configFile = useSettings((s) => s.configFile);
  const switching = useSettings((s) => s.switching);
  const modelSwitching = useModels((s) => s.pending !== null);
  const name = confName || t('app.title');

  // 服务端只回角色名；同名时优先标记本次连接中确认切到的文件。
  const currentFile =
    configs?.find((c) => c.filename === configFile && c.name === confName)?.filename ??
    configs?.find((c) => c.name === confName)?.filename;
  const defaultConfig = configs?.find((c) => c.filename === 'conf.yaml');
  const defaultMatch = defaultConfig
    ? configs?.find((c) => c.filename !== 'conf.yaml' && c.name === defaultConfig.name)
    : undefined;
  const visibleConfigs = (configs ?? []).filter(
    (c) => !(defaultMatch && c.filename === 'conf.yaml'),
  );
  const nameCounts = new Map<string, number>();
  for (const config of visibleConfigs) {
    nameCounts.set(config.name, (nameCounts.get(config.name) ?? 0) + 1);
  }
  const selectedId =
    defaultMatch && currentFile === defaultMatch.filename ? 'conf.yaml' : currentFile;

  return (
    <TopBarPicker
      kind="character"
      name={name}
      label={switching ? `${name} · ${t('status.switching')}` : t('character.pick', { name })}
      icon={<span className={DOT_CLASS[status] ?? 'dot'} />}
      menuTitle={t('character.title')}
      options={visibleConfigs.map((config) => {
        const isDefault = Boolean(config.is_default) || config.filename === 'conf.yaml' || config.filename === defaultMatch?.filename;
        return {
          id: defaultMatch && config.filename === defaultMatch.filename ? 'conf.yaml' : config.filename,
          name: config.name,
          description: isDefault ? t('character.default')
            : (nameCounts.get(config.name) ?? 0) > 1 ? config.filename.replace(/\.yaml$/, '') : undefined,
        };
      })}
      selectedId={selectedId}
      switching={switching}
      disabled={status !== 'online' || !confName || modelSwitching}
      busy={busy}
      statusText={switching ? t('status.switching') : statusText}
      emptyHint={t(configs === null ? 'character.loading' : 'character.empty')}
      onOpen={fetchConfigs}
      onSelect={(id) => { if (id !== null) switchConfig(id); }}
    />
  );
}
