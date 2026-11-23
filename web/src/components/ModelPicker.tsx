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

function resolveCatalogOptions(
  catalogState: ReturnType<typeof useModels.getState>['catalogs'][ModelKind],
  kind: ModelKind,
  t: ReturnType<typeof useTranslation>['t'],
) {
  const { options: catalog, current, characterDefault } = catalogState;
  const defaultId = characterDefault?.id;
  const pinnedDefault = current !== null && current === defaultId;
  const hasDefaultInCatalog = defaultId !== undefined && catalog.some((option) => option.id === defaultId);
  const options = hasDefaultInCatalog
    ? catalog.map((option) => (option.id === defaultId
      ? {
          id: null,
          name: option.name,
          description: t(pinnedDefault ? 'model.followAgain' : 'model.default'),
          reselect: pinnedDefault,
        }
      : {
          id: option.id,
          name: option.name,
        }))
    : [
        {
          id: null,
          name: characterDefault?.name ?? t('model.default'),
          description: t(pinnedDefault ? 'model.followAgain' : `model.defaultDesc.${kind}`),
          reselect: pinnedDefault,
        },
        ...catalog,
      ];
  const active = options.find((option) => option.id === (pinnedDefault ? null : current));
  const name = active?.name ?? current ?? options[0].name;
  return { options, active, name };
}

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

  const pillKind: ModelKind = available.includes('llm') ? 'llm' : kind;
  const { options, active, name } = resolveCatalogOptions(catalogs[kind], kind, t);
  const pillName = pillKind === kind
    ? name
    : resolveCatalogOptions(catalogs[pillKind], pillKind, t).name;
  const category = (id: ModelKind) => t(`model.category.${id}`);
  const label = pending ? t('model.switching', { category: category(pending.kind) }) :
    t('model.pick', { category: category(pillKind), name: pillName });

  return (
    <TopBarPicker
      kind="model"
      name={pillName}
      label={label}
      icon={ICONS[pillKind]}
      iconKey={pillKind}
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
