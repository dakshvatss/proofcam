import { Layers } from 'lucide-react'
import { useState } from 'react'
import type { PhotoInfo } from '../api/types'
import { cn } from '../lib/utils'
import { CardTitle } from './ui/card'

/** A captured photo with its saved overlay (drawn by the server on that same photo, never on the live preview). */
export function PhotoViewer({ photo }: { photo: PhotoInfo }) {
  const [showOverlay, setShowOverlay] = useState(true)
  const overlay = showOverlay && photo.overlay_url
  return (
    <figure className="overflow-hidden rounded-[var(--radius-panel)] border border-line bg-surface">
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <div className="flex min-w-0 items-baseline gap-2">
          <CardTitle>Photo {photo.seq}</CardTitle>
          {photo.superseded && <span className="text-xs text-fg-subtle">superseded</span>}
          {!photo.usable && <span className="text-xs text-warn">not usable</span>}
        </div>
        {photo.overlay_url ? (
          <button
            type="button"
            className={cn('inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors duration-150',
              showOverlay ? 'border-accent/40 bg-accent/10 text-accent-strong' : 'border-line-strong text-fg-muted hover:text-fg')}
            onClick={() => setShowOverlay((v) => !v)}
            aria-pressed={showOverlay}
          >
            <Layers className="h-3.5 w-3.5" aria-hidden /> {showOverlay ? 'Showing analysis overlay' : 'Showing original photo'}
          </button>
        ) : (
          <span className="text-xs text-fg-subtle">No overlay for this photo</span>
        )}
      </div>
      <img
        src={overlay ? photo.overlay_url! : photo.photo_url}
        alt={overlay ? `Analysis overlay for photo ${photo.seq}` : `Photo ${photo.seq}`}
        className="block w-full border-y border-line bg-black"
      />
      <figcaption className="px-4 py-3 text-xs leading-relaxed text-fg-subtle">
        {overlay
          ? "Filled shapes: SAM segmentation. Dashed boxes: Muse's claims. Overlays show what the models reported, not proof."
          : <>{photo.width}×{photo.height} px · the normalized image the models analysed</>}
      </figcaption>
    </figure>
  )
}

export function PhotoHistory({ photos, selected, onSelect }: { photos: PhotoInfo[]; selected: number | null; onSelect: (seq: number) => void }) {
  if (!photos.length) return null
  return (
    <section aria-label="Photo history">
      <CardTitle className="mb-2.5">Photos ({photos.length})</CardTitle>
      <ul className="-mx-1 flex gap-2.5 overflow-x-auto px-1 pb-1 [scrollbar-width:none]">
        {photos.map((p) => (
          <li key={p.seq} className="w-[88px] shrink-0">
            <button
              type="button"
              onClick={() => onSelect(p.seq)}
              className={cn('relative block w-full overflow-hidden rounded-[10px] border transition-[border-color,opacity] duration-150',
                selected === p.seq ? 'border-accent ring-1 ring-accent' : 'border-line hover:border-line-strong',
                p.superseded && 'opacity-45')}
              aria-label={`Show photo ${p.seq}`}
              aria-current={selected === p.seq ? 'true' : undefined}
            >
              <img src={p.overlay_url ?? p.photo_url} alt="" className="aspect-[4/3] w-full object-cover" />
              <span className="absolute left-1 top-1 rounded-md bg-black/70 px-1.5 font-mono text-[11px] tabular-nums text-white">{p.seq}</span>
            </button>
            <p className={cn('mt-1 truncate text-[11px]', !p.usable ? 'text-warn' : 'text-fg-subtle')}>
              {p.superseded ? 'superseded' : !p.usable ? 'not usable' : p.responding_to ? 'requested view' : 'free capture'}
            </p>
          </li>
        ))}
      </ul>
    </section>
  )
}
