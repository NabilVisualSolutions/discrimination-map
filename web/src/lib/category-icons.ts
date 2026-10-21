import {
  Ban, BookX, Bandage, CircleDot, FileSearch, Flag, Flame, Globe, Heart, HeartHandshake,
  Landmark, LifeBuoy, Megaphone, MessageSquareWarning, Moon, Newspaper, ShieldAlert,
  ShieldBan, TriangleAlert, UserX, X, ChevronDown, ChevronUp, PanelRightClose, PanelRightOpen,
  type IconNode,
} from "lucide"

// Icons come from the `lucide` package (https://lucide.dev, ISC licence) as
// plain node data, so the same source draws the DOM icons (components/LucideIcon)
// and the map marker bitmaps (iconSvg) with no React server renderer in the bundle.
export type { IconNode }
export const UI_ICONS = { X, ChevronDown, ChevronUp, PanelRightClose, PanelRightOpen }

// One icon per category in backend/lawref.py CATEGORIES. Colour is never the
// only differentiator: the icon carries the category on the rail, in lists,
// in chips and on the map. Choices stay calm on purpose: they name the kind of
// event or the group affected, never depict harm.
export const CATEGORY_ICONS: Record<string, IconNode> = {
  arson: Flame, // fire
  violence: Bandage, // physical attack, shown as injury/care rather than a weapon
  threat: TriangleAlert, // warning sign
  banned_symbol: Ban, // prohibited sign
  holocaust_denial: BookX, // denial of the historical record
  incitement: Megaphone, // speech aimed at a crowd
  propaganda: Newspaper, // printed/published material
  banned_org: ShieldBan, // prohibited organisation
  assembly: Flag, // march / rally
  far_right_mention: FileSearch, // catch-all, needs review
  racism: UserX, // a person singled out
  islamophobia: Moon, // crescent moon
  antisemitism: Landmark, // community institution (avoids a religious symbol)
  homophobia_transphobia: Heart, // heart
  neo_nazi: ShieldAlert, // extremist activity alert
  xenophobia: Globe, // hostility to people from elsewhere
  sexual_violence: LifeBuoy, // support, deliberately non-graphic
  harassment: MessageSquareWarning, // abusive message
  other: CircleDot, // anything else
  solidarity_event: HeartHandshake, // counter-protest / solidarity
}

/** First category of a report, lower-cased: the one lookup key used for colour, label and icon everywhere. */
export const catKey = (raw: string) => raw.split(/[,|/]/)[0]?.trim().toLowerCase() ?? ""
export const iconFor = (key: string): IconNode => CATEGORY_ICONS[key.toLowerCase()] ?? CircleDot

const attrs = (a: Record<string, string | number | undefined>) =>
  Object.entries(a).map(([k, v]) => ` ${k}="${String(v)}"`).join("")

/** Standalone SVG text for an icon (used to draw map marker bitmaps). */
export function iconSvg(node: IconNode, color: string, size: number, strokeWidth = 2): string {
  const body = node.map(([tag, a]) => `<${tag}${attrs(a)}/>`).join("")
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="${strokeWidth}" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`
}
