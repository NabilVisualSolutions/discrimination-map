import { describe, expect, it } from "vitest"
import { hasWebGL } from "./webgl"

describe("hasWebGL", () => {
  it("answers false instead of throwing where there is no document", () => {
    expect(hasWebGL()).toBe(false)
  })
})
