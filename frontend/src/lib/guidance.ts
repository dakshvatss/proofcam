import type { InspectionState, NextViewRequest } from '../api/types'

/**
 * The next-view request that still applies to the CURRENT installation configuration, or null.
 *
 * After an installation change the server keeps returning the last request of the previous configuration as
 * `next_view` (it was issued after a photo that no longer counts). That guidance described the old setup, so it is
 * hidden: the next photo is sent without `responding_to`, and the server plans fresh guidance from it.
 */
export function currentGuidance(st: InspectionState): NextViewRequest | null {
  const nv = st.next_view
  if (!nv || st.status !== 'open') return null
  const after = st.photos.find((p) => p.image_id === nv.after_image_id)
  if (after?.superseded) return null
  if (!after && st.epoch > 0) return null // issued after no known photo of this configuration: do not trust it
  return nv
}

/** True when guidance exists but belongs to a configuration that was replaced by a declared change. */
export function guidanceIsStale(st: InspectionState): boolean {
  return st.status === 'open' && st.next_view !== null && currentGuidance(st) === null
}
