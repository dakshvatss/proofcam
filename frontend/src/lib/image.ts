// Client-side preparation of gallery uploads. iPhone libraries hold HEIC photos of 12-48 MP; the server only needs
// a JPEG (it normalizes to 1600 px anyway). Re-encoding here also drops EXIF metadata such as GPS location.

export const UPLOAD_MAX_SIDE = 2400

export async function prepareUpload(file: File): Promise<{ blob: Blob; name: string }> {
  const original = { blob: file as Blob, name: file.name }
  if (typeof createImageBitmap !== 'function' || typeof document === 'undefined') return original
  let bmp: ImageBitmap
  try {
    bmp = await createImageBitmap(file, { imageOrientation: 'from-image' })
  } catch {
    return original // the browser cannot decode it; the server decides (it rejects undecodable images with 422)
  }
  try {
    const scale = Math.min(1, UPLOAD_MAX_SIDE / Math.max(bmp.width, bmp.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(bmp.width * scale))
    canvas.height = Math.max(1, Math.round(bmp.height * scale))
    const ctx = canvas.getContext('2d')
    if (!ctx) return original
    ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, 'image/jpeg', 0.9))
    if (!blob) return original
    return { blob, name: file.name.replace(/\.[^.]+$/, '') + '.jpg' }
  } finally {
    bmp.close()
  }
}

export function isIOS(): boolean {
  if (typeof navigator === 'undefined') return false
  return /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

export function isStandalone(): boolean {
  if (typeof window === 'undefined') return false
  return window.matchMedia?.('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true
}
