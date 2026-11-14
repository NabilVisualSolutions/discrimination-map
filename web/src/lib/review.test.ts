import { describe, expect, it } from "vitest"
import { isHuman } from "./review"

describe("isHuman", () => {
  it("is true only for a verified row a person reviewed", () => {
    expect(isHuman({ status: "verified", human_verified: true })).toBe(true)
    expect(isHuman({ status: "verified", human_verified: false })).toBe(false)
    expect(isHuman({ status: "unverified", human_verified: true })).toBe(false)
  })
})
