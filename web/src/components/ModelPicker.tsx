import { useTranslation } from 'react-i18next';
import { useModels } from '../stores/models';
import { fetchModels, switchModel } from '../services/actions';
import { TopBarPicker } from './TopBarPicker';
import { SparkIcon } from './icons';

// 后台没有配置可选模型（或当前账号一个都不可用）时整个不渲染。
export function ModelPicker() {
  const { t } = useTranslation();
  const models = useModels((s) => s.models);
  const current = useModels((s) => s.current);
  const switching = useModels((s) => s.switching);
  if (models.length === 0) return null;

  const options = [
    { id: null, name: t('model.default'), description: t('model.defaultDesc') },
    ...models,
  ];
  const active = options.find((option) => option.id === current) ?? options[0];

  return (
    <TopBarPicker
      kind="model"
      name={active.name}
      label={t('model.pick', { name: active.name })}
      icon={<SparkIcon />}
      menuTitle={t('model.title')}
      options={options}
      selectedId={active.id}
      switching={switching}
      // 每次打开都刷新，后台更改目录或权限后能即时看到。
      onOpen={fetchModels}
      onSelect={switchModel}
    />
  );
}
