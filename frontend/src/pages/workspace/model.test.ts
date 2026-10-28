import { describe, expect, it } from 'vitest'
import type { FileInfo } from '../../components/FileTable'
import { buildRequest, EMPTY_DEFAULTS, initialOutput, makeItem, usesAdvancedPath, withOutput, type WorkspaceDefaults } from './model'

const video: FileInfo = {
  id: 'file-1',
  original_filename: 'clip.mkv',
  media_type: 'mkv',
  extension: '.mkv',
  size_bytes: 1000,
  compatible_formats: { mp4: ['low', 'medium', 'high'], webm: ['low', 'medium', 'high'], mp3: [] },
}

const defaults: WorkspaceDefaults = {
  ...EMPTY_DEFAULTS,
  compressibleFormats: new Set(['mkv']),
  compressionLevelsByFormat: { mkv: ['light', 'balanced', 'max'] },
}

describe('workspace request builder', () => {
  it('sends the classic compression body when nothing advanced is set', () => {
    const item = makeItem(video, defaults)
    expect(item.output).toBe('')
    const request = buildRequest(item)
    expect(request.endpoint).toBe('/api/compression-jobs')
    expect(request.body).toEqual({ id: 'file-1', compression_level: 'balanced' })
    expect(usesAdvancedPath(item)).toBe(false)
  })

  it('sends the classic conversion body with the default quality', () => {
    const item = withOutput(makeItem(video, defaults), 'mp4', defaults)
    expect(buildRequest(item)).toEqual({
      kind: 'convert',
      endpoint: '/api/jobs',
      body: { id: 'file-1', output_format: 'mp4', quality: 'medium' },
    })
  })

  it('only sends options the user set, and drops empty sections', () => {
    const item = {
      ...makeItem(video, defaults),
      preset: 'amd-fast-hevc',
      options: { video: { codec: 'hevc' as const, crf: undefined }, audio: {}, strip_metadata: undefined },
    }
    expect(buildRequest(item).body).toEqual({
      id: 'file-1',
      compression_level: 'balanced',
      preset: 'amd-fast-hevc',
      options: { video: { codec: 'hevc' } },
    })
    expect(usesAdvancedPath(item)).toBe(true)
  })

  it('resets encode settings when the target format changes', () => {
    const item = { ...makeItem(video, defaults), preset: 'x', options: { video: { codec: 'vp9' as const } } }
    const moved = withOutput(item, 'mp4', defaults)
    expect(moved.options).toEqual({})
    expect(moved.preset).toBeUndefined()
  })

  it('prefers the user default conversion over compression', () => {
    expect(initialOutput(video, { ...defaults, defaultFormats: { mkv: 'mp4' } })).toBe('mp4')
    expect(initialOutput(video, defaults)).toBe('')
    expect(initialOutput(video, EMPTY_DEFAULTS)).toBe('mp3')
  })
})
