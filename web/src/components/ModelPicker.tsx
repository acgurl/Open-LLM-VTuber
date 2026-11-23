import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { MODEL_KINDS, type ModelKind } from '../protocol/types';
import { useConnection } from '../stores/connection';
import { useModels } from '../stores/models';
import { useSettings } from '../stores/settings';
import { fetchModels, switchModel } from '../services/actions';
import { TopBarPicker } from './TopBarPicker';
import { MicIcon, SparkIcon, VolumeIcon } from './icons';

const ICONS = {
  llm: <SparkIcon />,
  tts: <VolumeIcon muted={false} />,
  asr: <MicIcon on />,
};

export function ModelPicker() {
  const { t } = useTranslation();
  const catalogs = useModels((s) => s.catalogs);
  const pending = useModels((s) => s.pending);
  const online = useConnection((s) => s.status === 'online');
  const characterSwitching = useSettings((s) => s.switching);
  const [preferredKind, setPreferredKind] = useState<ModelKind>('llm');
  const available = MODEL_KINDS.filter((kind) => catalogs[kind].options.length > 0);
  const kind = available.includes(preferredKind) ? preferredKind : available[0];
  if (!kind) return null;

  const { options: catalog, current, characterDefault } = catalogs[kind];
  const defaultId = characterDefault?.id;
  const pinnedDefault = current !== null && current === defaultId;
  const options = [
    {
      id: null,
      name: characterDefault?.name ?? t('model.default'),
      description: t(pinnedDefault ? 'model.followAgain' : `model.defaultDesc.${kind}`),
      reselect: pinnedDefault,
    },
    ...catalog.filter((option) => option.id !== defaultId),
  ];
  const active = options.find((option) => option.id === (pinnedDefault ? null : current));
  const name = active?.name ?? current ?? options[0].name;
  const category = (id: ModelKind) => t(`model.category.${id}`);
  const label = pending ? t('model.switching', { category: category(pending.kind) }) :
    t('model.pick', { category: category(kind), name });

  return (
    <TopBarPicker
      kind="model"
      name={name}
      label={label}
      icon={ICONS[kind]}
      iconKey={kind}
      menuTitle={available.length > 1 ? t('model.title') : category(kind)}
      options={options}
      selectedId={active?.id}
      disabled={!online || characterSwitching}
      switching={pending !== null}
      tabs={available.length > 1 ? {
        items: available.map((id) => ({ id, label: t(`model.tab.${id}`), icon: ICONS[id], title: category(id) })),
        activeId: kind,
        onChange: (id) => {
          const next = available.find((candidate) => candidate === id);
          if (next) setPreferredKind(next);
        },
      } : undefined}
      // 每次打开都刷新，后台更改目录或权限后能即时看到。
      onOpen={fetchModels}
      onSelect={(id) => switchModel(id, kind)}
    />
  );
}
