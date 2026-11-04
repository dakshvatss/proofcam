import { CircleCheck, CircleDashed, CircleX, type LucideIcon } from 'lucide-react'
import type { RequirementStatus } from '../api/types'

/** Visual language of the three verdicts. Distinct by colour, icon AND wording, so they never depend on colour
 * alone. Insufficient evidence is presented as an inspection outcome with a next step, not as an error. */
export const VERDICT: Record<RequirementStatus, { icon: LucideIcon; text: string; tint: string; badge: 'ok' | 'bad' | 'warn'; caption: string }> = {
  VERIFIED: { icon: CircleCheck, text: 'text-ok', tint: 'bg-[#effaf4] border-ok/15', badge: 'ok', caption: 'Proven by the photos.' },
  VIOLATED: { icon: CircleX, text: 'text-bad', tint: 'bg-[#fff3f2] border-bad/15', badge: 'bad', caption: 'Clearly observed not to meet the requirement.' },
  INSUFFICIENT_EVIDENCE: {
    icon: CircleDashed, text: 'text-warn', tint: 'bg-[#fff9f0] border-warn/15', badge: 'warn',
    caption: 'Not proven yet. The facts below are still unobserved.',
  },
}

