import { createElement } from "react"
import type { IconNode } from "./category-icons"

/** Draws a Lucide icon node as an inline SVG (decorative: pair it with a text label). */
export function LucideIcon({ node, className, strokeWidth = 2 }: { node: IconNode; className?: string; strokeWidth?: number }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      {node.map(([tag, a], i) => createElement(tag, { key: i, ...a }))}
    </svg>
  )
}
