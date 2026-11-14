import { Component, type ReactNode } from "react"

// If the map throws anyway (lost WebGL context, a driver bug), show the
// fallback in its place. The list, table and filters keep working.
export class MapBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children
  }
}
