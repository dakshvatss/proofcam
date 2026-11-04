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
    <figure className="overflow-hidden rounded-[var(--radius-panel)] border border-line bg-surface shadow-[var(--shadow-card)]">
      <div className="flex items-center justify-between gap-3 px-5 py-3.5">
        <div className="flex min-w-0 items-baseline gap-2.5">
          <CardTitle>Photo {photo.seq}</CardTitle>
          {photo.superseded && <span className="text-xs text-fg-subtle">superseded</span>}
          {!photo.usable && <span className="text-xs font-medium text-warn">not usable</span>}
        </div>
        {photo.overlay_url ? (
          <button
            type="button"
            className={cn('inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-semibold transition-colors duration-150',
              showOverlay ? 'border-accent/30 bg-accent-soft text-accent-strong' : 'border-line-strong bg-surface text-fg-muted hover:text-fg')}
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
        className="block w-full border-y border-line bg-viewport"
      />
      <figcaption className="px-5 py-3.5 text-[13px] leading-relaxed text-fg-subtle">
        {overlay ? (
          <span className="grid gap-1.5 sm:grid-cols-2">
            <span className="flex items-start gap-2">
              <span aria-hidden className="mt-1 h-3 w-3 shrink-0 rounded-sm bg-[#3fbfad]/70" />
              <span><span className="font-semibold text-fg">Filled shapes:</span> SAM segmentation of equipment and cables.</span>
            </span>
            <span className="flex items-start gap-2">
              <span aria-hidden className="mt-1 h-3 w-3 shrink-0 rounded-sm border-2 border-dashed border-fg-subtle" />
              <span><span className="font-semibold text-fg">Dashed boxes:</span> what Muse reported seeing.</span>
            </span>
            <span className="sm:col-span-2">Overlays show what the models reported, not proof. The evidence list shows what the policy accepted.</span>
          </span>
        ) : <>{photo.width}×{photo.height} px · the normalized image the models analysed</>}
      </figcaption>
    </figure>
  )
}

export function PhotoHistory({ photos, selected, onSelect }: { photos: PhotoInfo[]; selected: number | null; onSelect: (seq: number) => void }) {
  if (!photos.length) return null
  return (
    <section aria-label="Photo history">
      <CardTitle className="mb-3">Photos ({photos.length})</CardTitle>
      <ul className="-mx-1 flex gap-3 overflow-x-auto px-1 pb-1 [scrollbar-width:none]">
        {photos.map((p) => (
          <li key={p.seq} className="w-24 shrink-0">
            <button
              type="button"
              onClick={() => onSelect(p.seq)}
              className={cn('relative block w-full overflow-hidden rounded-xl border-2 bg-viewport transition-[border-color,opacity,box-shadow] duration-150',
                selected === p.seq ? 'border-accent shadow-[0_0_0_3px_rgb(8_102_255/0.15)]' : 'border-transparent hover:border-line-strong',
                p.superseded && 'opacity-45')}
              aria-label={`Show photo ${p.seq}`}
              aria-current={selected === p.seq ? 'true' : undefined}
            >
              <img src={p.overlay_url ?? p.photo_url} alt="" className="aspect-[4/3] w-full object-cover" />
              <span className="absolute left-1.5 top-1.5 rounded-md bg-black/65 px-1.5 text-[11px] font-semibold tabular-nums text-white">{p.seq}</span>
            </button>
            <p className={cn('mt-1.5 truncate text-xs', !p.usable ? 'font-medium text-warn' : 'text-fg-subtle')}>
              {p.superseded ? 'superseded' : !p.usable ? 'not usable' : p.responding_to ? 'requested view' : 'free capture'}
            </p>
          </li>
        ))}
      </ul>
    </section>
  )
}
