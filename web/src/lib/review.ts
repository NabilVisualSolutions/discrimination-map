import type { Report } from "./api"

/** Only a person's review counts. A "verified" status set by a bulk script is not human review. */
export const isHuman = (r: Pick<Report, "status" | "human_verified">) => r.status === "verified" && r.human_verified === true
