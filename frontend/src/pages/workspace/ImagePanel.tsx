import { useTranslation } from 'react-i18next'
import { AutoSlider, Field, Segmented, Toggle } from '../../ui/controls'
import type { ChromaSubsampling, EncodeOptions, ImageFormatInfo, ImageOptions, Preset, ProbeResult } from '../../utils/encoding'
import type { WorkspaceItem } from './model'

const DIMENSIONS = [3840, 2560, 1920, 1280, 1024, 640]
const PALETTE_SIZES = [256, 128, 64, 32, 16]

function clean<T extends object>(value: T): T {
  return Object.fromEntries(Object.entries(value).filter(([, v]) => v !== undefined)) as T
}

export default function ImagePanel({
  item,
  format,
  presets,
  probe,
  compress,
  onChange,
}: {
  item: WorkspaceItem
  format: ImageFormatInfo
  presets: Preset[]
  probe: ProbeResult | null | undefined
  compress: boolean
  onChange: (options: EncodeOptions) => void
}) {
  const { t } = useTranslation()
  const options = item.options
  const own: ImageOptions = options.image ?? {}
  const inherited: ImageOptions = presets.find(p => p.id === item.preset)?.options.image ?? {}
  const lossless = own.lossless ?? inherited.lossless ?? false
  const longest = probe?.image ? Math.max(probe.image.width, probe.image.height) : undefined

  const setImage = (patch: Partial<ImageOptions>) => {
    const next = clean({ ...own, ...patch })
    onChange(clean({ ...options, image: Object.keys(next).length ? next : undefined }))
  }
  const setTop = (patch: Partial<EncodeOptions>) => onChange(clean({ ...options, ...patch }))

  return (
    <div className="space-y-5">
      <section className="space-y-3">
        <h3 className="text-xs font-medium text-text">{t('workspace.image.title')}</h3>
        {format.lossless && (
          <Field group label={t('workspace.image.encoding')}>
            <Segmented<string>
              ariaLabel={t('workspace.image.encoding')}
              value={own.lossless === undefined ? '' : own.lossless ? 'lossless' : 'lossy'}
              onChange={value => setImage({ lossless: value === '' ? undefined : value === 'lossless', ...(value === 'lossless' ? { quality: undefined } : {}) })}
              options={[
                { value: '', label: t('workspace.auto') },
                { value: 'lossy', label: t('workspace.image.lossy') },
                { value: 'lossless', label: t('workspace.image.lossless') },
              ]}
            />
          </Field>
        )}
        {format.quality && !lossless && (
          <AutoSlider
            label={t('workspace.image.quality')}
            value={own.quality}
            fallback={inherited.quality ?? 80}
            min={1}
            max={100}
            autoText={inherited.quality !== undefined ? t('workspace.inheritedValue', { value: inherited.quality }) : t('workspace.auto')}
            resetLabel={t('workspace.reset')}
            onChange={quality => setImage({ quality })}
          />
        )}
        {format.effort && (
          <>
            <AutoSlider
              label={t('workspace.image.effort')}
              value={own.effort}
              fallback={inherited.effort ?? 6}
              min={0}
              max={10}
              autoText={inherited.effort !== undefined ? t('workspace.inheritedValue', { value: inherited.effort }) : t('workspace.auto')}
              resetLabel={t('workspace.reset')}
              onChange={effort => setImage({ effort })}
            />
            <p className="text-[11px] text-text-muted">{t('workspace.image.effortHint')}</p>
          </>
        )}
        {format.chroma_subsampling && !lossless && (
          <Field group label={t('workspace.image.chroma')}>
            <Segmented<string>
              ariaLabel={t('workspace.image.chroma')}
              mono
              value={own.chroma_subsampling ?? ''}
              onChange={value => setImage({ chroma_subsampling: (value || undefined) as ChromaSubsampling | undefined })}
              options={[
                { value: '', label: t('workspace.auto') },
                { value: '4:2:0', label: '4:2:0' },
                { value: '4:2:2', label: '4:2:2' },
                { value: '4:4:4', label: '4:4:4' },
              ]}
            />
          </Field>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('workspace.image.maxDimension')}>
            <select
              className="field-control font-mono"
              value={own.max_dimension ?? ''}
              onChange={event => setImage({ max_dimension: event.target.value ? Number(event.target.value) : undefined })}
            >
              <option value="">{inherited.max_dimension ? t('workspace.inheritedValue', { value: `${inherited.max_dimension}px` }) : t('workspace.source')}</option>
              {DIMENSIONS.filter(d => !longest || d < longest).map(d => <option key={d} value={d}>{d}px</option>)}
            </select>
          </Field>
          {format.palette_colors && (
            <Field label={t('workspace.image.paletteColors')}>
              <select
                className="field-control font-mono"
                value={own.palette_colors ?? ''}
                onChange={event => setImage({ palette_colors: event.target.value ? Number(event.target.value) : undefined })}
              >
                <option value="">{t('workspace.image.fullColor')}</option>
                {PALETTE_SIZES.map(n => <option key={n} value={n}>{n}</option>)}
              </select>
            </Field>
          )}
        </div>
      </section>

      <section className="flex flex-wrap gap-x-5 gap-y-2">
        <Toggle checked={options.strip_metadata === true} onChange={checked => setTop({ strip_metadata: checked || undefined })}>
          {t('workspace.image.stripExif')}
        </Toggle>
        {compress && (
          <Toggle checked={options.keep_if_larger === true} onChange={checked => setTop({ keep_if_larger: checked || undefined })}>
            {t('workspace.extras.keepIfLarger')}
          </Toggle>
        )}
      </section>
    </div>
  )
}
