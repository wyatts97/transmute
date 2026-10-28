import { useTranslation } from 'react-i18next'
import { AutoSlider, Field, Segmented, Toggle } from '../../ui/controls'
import type {
  AudioCodec,
  AudioOptions,
  Capabilities,
  ContainerInfo,
  EncodeOptions,
  Preset,
  ProbeResult,
  VideoCodec,
  VideoOptions,
} from '../../utils/encoding'
import { effectiveVideo, encodersForCodec, type WorkspaceItem } from './model'

const CODEC_ORDER: VideoCodec[] = ['h264', 'hevc', 'av1', 'vp9']
const CODEC_LABELS: Record<string, string> = { h264: 'H.264', hevc: 'HEVC', av1: 'AV1', vp9: 'VP9' }
const AUDIO_LABELS: Record<string, string> = {
  aac: 'AAC', opus: 'Opus', mp3: 'MP3', flac: 'FLAC', ac3: 'AC-3', vorbis: 'Vorbis', pcm: 'PCM',
}
const HEIGHTS = [2160, 1440, 1080, 720, 480]
const FRAME_RATES = [60, 50, 30, 25, 24]
const AUDIO_BITRATES = [64, 96, 128, 160, 192, 256, 320]
const LOSSLESS_OR_PASSTHROUGH = new Set(['flac', 'pcm', 'copy', 'none'])

type RateMode = 'quality' | 'target_size' | 'bitrate'

function clean<T extends object>(value: T): T {
  return Object.fromEntries(Object.entries(value).filter(([, v]) => v !== undefined)) as T
}

function numberOrUndefined(raw: string): number | undefined {
  if (raw.trim() === '') return undefined
  const value = Number(raw)
  return Number.isFinite(value) ? value : undefined
}

export default function VideoPanel({
  item,
  container,
  caps,
  presets,
  probe,
  compress,
  onChange,
}: {
  item: WorkspaceItem
  container: ContainerInfo
  caps: Capabilities | null
  presets: Preset[]
  probe: ProbeResult | null | undefined
  compress: boolean
  onChange: (options: EncodeOptions) => void
}) {
  const { t } = useTranslation()
  const options = item.options
  const own: VideoOptions = options.video ?? {}
  const ownAudio: AudioOptions = options.audio ?? {}
  const isVideo = container.kind === 'video'
  const { codec, encoder, inherited } = effectiveVideo(item, presets, container, caps)
  const presetAudio = presets.find(p => p.id === item.preset)?.options.audio ?? {}

  const setVideo = (patch: Partial<VideoOptions>, reset: (keyof VideoOptions)[] = []) => {
    const next: VideoOptions = { ...own, ...patch }
    for (const key of reset) delete next[key]
    onChange(clean({ ...options, video: Object.keys(clean(next)).length ? clean(next) : undefined }))
  }
  const setAudio = (patch: Partial<AudioOptions>) => {
    const next = clean({ ...ownAudio, ...patch })
    onChange(clean({ ...options, audio: Object.keys(next).length ? next : undefined }))
  }
  const setTop = (patch: Partial<EncodeOptions>) => onChange(clean({ ...options, ...patch }))

  const encoders = encodersForCodec(caps, codec)
  const softwareTwin = encoders.find(e => !e.hardware)
  const hasGpu = (caps?.hardware.encoders.length ?? 0) > 0
  const codecHasGpu = encoders.some(e => e.hardware)
  const isCopy = codec === 'copy'
  const tenBitRequested = (own.bit_depth ?? inherited.bit_depth) === 10

  const rateMode: RateMode = own.rate_control === 'target_size'
    ? 'target_size'
    : own.rate_control === 'vbr' || own.rate_control === 'cbr' ? 'bitrate' : 'quality'

  const qualityParam = encoder?.quality_param ?? 'crf'
  const ownQuality = qualityParam === 'qp' ? own.qp ?? own.crf : own.crf
  const inheritedQuality = qualityParam === 'qp' ? inherited.qp ?? inherited.crf : inherited.crf
  const autoAudio = container.default_audio ?? undefined
  const effectiveAudioCodec = ownAudio.codec ?? presetAudio.codec ?? autoAudio
  const audioBitrateLocked = LOSSLESS_OR_PASSTHROUGH.has(effectiveAudioCodec ?? '')

  let note: string | null = null
  if (isVideo && !isCopy) {
    if (encoder?.hardware) {
      note = t('workspace.video.gpuNote', { device: caps?.hardware.vaapi_device ?? '', fallback: softwareTwin?.name ?? '' })
    } else if (hasGpu && codec && !codecHasGpu) {
      note = t('workspace.video.noGpuForCodec', { codec: CODEC_LABELS[codec] ?? codec })
    } else if (hasGpu && codecHasGpu && tenBitRequested && !own.encoder) {
      note = t('workspace.video.gpuNo10bit')
    }
  }

  return (
    <div className="space-y-5">
      {isVideo && (
        <section className="space-y-3">
          <h3 className="text-xs font-medium text-text">{t('workspace.video.title')}</h3>
          <Field group label={t('workspace.video.codec')}>
            <Segmented<string>
              ariaLabel={t('workspace.video.codec')}
              value={own.codec ?? ''}
              onChange={value => setVideo({ codec: (value || undefined) as VideoCodec | undefined }, ['encoder', 'crf', 'qp', 'encoder_preset', 'tune', 'rate_control', 'bitrate_kbps', 'maxrate_kbps'])}
              options={[
                { value: '', label: t('workspace.auto'), hint: container.default_video ? CODEC_LABELS[container.default_video] : undefined },
                ...CODEC_ORDER.filter(c => container.video_codecs.includes(c)).map(c => ({ value: c, label: CODEC_LABELS[c] })),
                { value: 'copy', label: t('workspace.video.copy'), hint: t('workspace.video.copyHint') },
              ]}
            />
          </Field>

          {!isCopy && encoders.length > 0 && (
            <Field group label={t('workspace.video.encoder')}>
              <Segmented<string>
                ariaLabel={t('workspace.video.encoder')}
                mono
                value={own.encoder ?? ''}
                onChange={value => setVideo({ encoder: value || undefined }, ['crf', 'qp', 'encoder_preset', 'tune'])}
                options={[
                  { value: '', label: t('workspace.auto'), hint: encoder?.name },
                  ...encoders.map(e => ({
                    value: e.name,
                    label: `${e.hardware ? t('workspace.video.gpu') : t('workspace.video.cpu')} · ${e.name}`,
                  })),
                ]}
              />
            </Field>
          )}
          {note && <p className="text-[11px] text-text-muted">{note}</p>}

          {!isCopy && encoder && (
            <>
              <Field group label={t('workspace.video.rateControl')}>
                <Segmented<RateMode>
                  ariaLabel={t('workspace.video.rateControl')}
                  value={rateMode}
                  onChange={mode => {
                    if (mode === 'quality') setVideo({}, ['rate_control', 'bitrate_kbps', 'maxrate_kbps', 'target_size_mb'])
                    else if (mode === 'target_size') setVideo({ rate_control: 'target_size' }, ['bitrate_kbps', 'maxrate_kbps', 'crf', 'qp'])
                    else setVideo({ rate_control: 'vbr' }, ['target_size_mb', 'crf', 'qp'])
                  }}
                  options={[
                    { value: 'quality', label: t('workspace.video.constantQuality') },
                    { value: 'target_size', label: t('workspace.video.targetSize'), disabled: !encoder.rate_controls.includes('target_size') },
                    { value: 'bitrate', label: t('workspace.video.bitrate'), disabled: !encoder.rate_controls.includes('vbr') },
                  ]}
                />
              </Field>

              {rateMode === 'quality' && (
                <AutoSlider
                  label={qualityParam.toUpperCase()}
                  value={ownQuality}
                  fallback={inheritedQuality ?? encoder.default_quality}
                  min={encoder.quality_range[0]}
                  max={encoder.quality_range[1]}
                  autoText={inheritedQuality !== undefined ? t('workspace.inheritedValue', { value: inheritedQuality }) : t('workspace.autoValue', { value: encoder.default_quality })}
                  resetLabel={t('workspace.reset')}
                  onChange={value => setVideo(qualityParam === 'qp' ? { qp: value } : { crf: value }, qualityParam === 'qp' ? ['crf'] : ['qp'])}
                />
              )}
              {rateMode === 'quality' && (
                <p className="text-[11px] text-text-muted">{t('workspace.video.qualityHint')}</p>
              )}

              {rateMode === 'target_size' && (
                <div className="grid grid-cols-2 gap-3">
                  <Field label={t('workspace.video.targetSizeMb')}>
                    <input
                      type="number"
                      min={0.1}
                      step={0.1}
                      className="field-control font-mono"
                      value={own.target_size_mb ?? ''}
                      onChange={event => setVideo({ target_size_mb: numberOrUndefined(event.target.value) })}
                    />
                  </Field>
                  <p className="self-end pb-1 text-[11px] text-text-muted">
                    {encoder.two_pass ? t('workspace.video.twoPass') : t('workspace.video.singlePass')}
                  </p>
                </div>
              )}

              {rateMode === 'bitrate' && (
                <div className="grid grid-cols-2 gap-3">
                  <Field label={t('workspace.video.bitrateKbps')}>
                    <input
                      type="number"
                      min={100}
                      step={100}
                      className="field-control font-mono"
                      value={own.bitrate_kbps ?? ''}
                      onChange={event => setVideo({ bitrate_kbps: numberOrUndefined(event.target.value) })}
                    />
                  </Field>
                  <Field label={t('workspace.video.maxrateKbps')}>
                    <input
                      type="number"
                      min={100}
                      step={100}
                      className="field-control font-mono"
                      value={own.maxrate_kbps ?? ''}
                      disabled={own.rate_control === 'cbr'}
                      onChange={event => setVideo({ maxrate_kbps: numberOrUndefined(event.target.value) })}
                    />
                  </Field>
                  {encoder.rate_controls.includes('cbr') && (
                    <Toggle
                      checked={own.rate_control === 'cbr'}
                      onChange={checked => setVideo({ rate_control: checked ? 'cbr' : 'vbr' }, checked ? ['maxrate_kbps'] : [])}
                    >
                      {t('workspace.video.constantBitrate')}
                    </Toggle>
                  )}
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                {encoder.presets.length > 0 && (
                  <Field label={t('workspace.video.speed')}>
                    <select
                      className="field-control font-mono"
                      value={own.encoder_preset === undefined ? '' : String(own.encoder_preset)}
                      onChange={event => {
                        const raw = event.target.value
                        const numeric = encoder.presets.some(p => typeof p === 'number')
                        setVideo({ encoder_preset: raw === '' ? undefined : numeric ? Number(raw) : raw })
                      }}
                    >
                      <option value="">{t('workspace.autoValue', { value: inherited.encoder_preset ?? encoder.default_preset ?? '' })}</option>
                      {encoder.presets.map(p => <option key={String(p)} value={String(p)}>{String(p)}</option>)}
                    </select>
                  </Field>
                )}
                {encoder.tunes.length > 0 && (
                  <Field label={t('workspace.video.tune')}>
                    <select
                      className="field-control"
                      value={own.tune ?? ''}
                      onChange={event => setVideo({ tune: event.target.value || undefined })}
                    >
                      <option value="">{t('workspace.none')}</option>
                      {encoder.tunes.map(tune => <option key={tune} value={tune}>{tune}</option>)}
                    </select>
                  </Field>
                )}
              </div>
              {encoder.presets.some(p => typeof p === 'number') && (
                <p className="text-[11px] text-text-muted">{t('workspace.video.numericPresetHint')}</p>
              )}

              <div className="grid grid-cols-3 gap-3">
                <Field label={t('workspace.video.resolution')}>
                  <select
                    className="field-control font-mono"
                    value={own.max_height ?? ''}
                    onChange={event => setVideo({ max_height: numberOrUndefined(event.target.value) }, ['max_width'])}
                  >
                    <option value="">{inherited.max_height ? t('workspace.inheritedValue', { value: `${inherited.max_height}p` }) : t('workspace.source')}</option>
                    {HEIGHTS.filter(h => !probe?.video?.height || h < probe.video.height).map(h => <option key={h} value={h}>{h}p</option>)}
                  </select>
                </Field>
                <Field label={t('workspace.video.frameRate')}>
                  <select
                    className="field-control font-mono"
                    value={own.fps ?? ''}
                    onChange={event => setVideo({ fps: numberOrUndefined(event.target.value) })}
                  >
                    <option value="">{inherited.fps ? t('workspace.inheritedValue', { value: inherited.fps }) : t('workspace.source')}</option>
                    {FRAME_RATES.map(f => <option key={f} value={f}>{f}</option>)}
                  </select>
                </Field>
                <Field label={t('workspace.video.bitDepth')}>
                  <select
                    className="field-control font-mono"
                    value={own.bit_depth ?? ''}
                    onChange={event => setVideo({ bit_depth: numberOrUndefined(event.target.value) as 8 | 10 | undefined })}
                  >
                    <option value="">{t('workspace.autoValue', { value: `${inherited.bit_depth ?? 8}-bit` })}</option>
                    <option value="8">8-bit</option>
                    <option value="10" disabled={!encoder.bit_depths.includes(10)}>10-bit</option>
                  </select>
                </Field>
              </div>
            </>
          )}
        </section>
      )}

      <section className="space-y-3">
        <h3 className="text-xs font-medium text-text">{t('workspace.audio.title')}</h3>
        <div className="grid grid-cols-3 gap-3">
          <Field label={t('workspace.audio.codec')}>
            <select
              className="field-control"
              value={ownAudio.codec ?? ''}
              onChange={event => {
                const value = (event.target.value || undefined) as AudioCodec | undefined
                setAudio(LOSSLESS_OR_PASSTHROUGH.has(value ?? '') ? { codec: value, bitrate_kbps: undefined } : { codec: value })
              }}
            >
              <option value="">{t('workspace.autoValue', { value: AUDIO_LABELS[presetAudio.codec ?? autoAudio ?? ''] ?? presetAudio.codec ?? autoAudio ?? '' })}</option>
              {container.audio_codecs.map(c => <option key={c} value={c}>{AUDIO_LABELS[c] ?? c}</option>)}
              <option value="copy">{t('workspace.audio.copy')}</option>
              {isVideo && <option value="none">{t('workspace.audio.remove')}</option>}
            </select>
          </Field>
          <Field label={t('workspace.audio.bitrate')}>
            <select
              className="field-control font-mono"
              value={ownAudio.bitrate_kbps ?? ''}
              disabled={audioBitrateLocked}
              onChange={event => setAudio({ bitrate_kbps: numberOrUndefined(event.target.value) })}
            >
              <option value="">{presetAudio.bitrate_kbps ? t('workspace.inheritedValue', { value: `${presetAudio.bitrate_kbps}k` }) : t('workspace.auto')}</option>
              {AUDIO_BITRATES.map(b => <option key={b} value={b}>{b}k</option>)}
            </select>
          </Field>
          <Field label={t('workspace.audio.channels')}>
            <select
              className="field-control"
              value={ownAudio.channels ?? ''}
              disabled={effectiveAudioCodec === 'copy' || effectiveAudioCodec === 'none'}
              onChange={event => setAudio({ channels: numberOrUndefined(event.target.value) })}
            >
              <option value="">{t('workspace.source')}</option>
              <option value="2">{t('workspace.audio.stereo')}</option>
              <option value="1">{t('workspace.audio.mono')}</option>
            </select>
          </Field>
        </div>
      </section>

      <section className="space-y-3">
        <h3 className="text-xs font-medium text-text">{t('workspace.extras.title')}</h3>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('workspace.extras.trimStart')}>
            <input
              type="number"
              min={0}
              step={0.1}
              className="field-control font-mono"
              value={options.trim?.start_s ?? ''}
              onChange={event => {
                const start = numberOrUndefined(event.target.value)
                const trim = clean({ ...(options.trim ?? {}), start_s: start })
                setTop({ trim: Object.keys(trim).length ? trim : undefined })
              }}
            />
          </Field>
          <Field label={t('workspace.extras.trimEnd')}>
            <input
              type="number"
              min={0}
              step={0.1}
              className="field-control font-mono"
              value={options.trim?.end_s ?? ''}
              onChange={event => {
                const end = numberOrUndefined(event.target.value)
                const trim = clean({ ...(options.trim ?? {}), end_s: end })
                setTop({ trim: Object.keys(trim).length ? trim : undefined })
              }}
            />
          </Field>
        </div>
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          {isVideo && container.subtitle_copy && (
            <Toggle checked={options.subtitles === 'copy'} onChange={checked => setTop({ subtitles: checked ? 'copy' : undefined })}>
              {t('workspace.extras.copySubtitles')}
            </Toggle>
          )}
          <Toggle checked={options.strip_metadata === true} onChange={checked => setTop({ strip_metadata: checked || undefined })}>
            {t('workspace.extras.stripMetadata')}
          </Toggle>
          {compress && (
            <Toggle checked={options.keep_if_larger === true} onChange={checked => setTop({ keep_if_larger: checked || undefined })}>
              {t('workspace.extras.keepIfLarger')}
            </Toggle>
          )}
          {encoder?.hardware && (
            <Toggle checked={options.hw_fallback !== false} onChange={checked => setTop({ hw_fallback: checked ? undefined : false })}>
              {t('workspace.extras.hwFallback')}
            </Toggle>
          )}
        </div>
      </section>
    </div>
  )
}
