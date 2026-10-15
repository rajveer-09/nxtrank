/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 14 October 2026
 */
// Loaded on demand (the artwork is ~200 kB), so it never delays the first paint.
import { createAvatar } from "@dicebear/core";
import * as lorelei from "@dicebear/lorelei";

/** An anime-style face for this seed, as a data: URI; the same seed always gives the same face. */
export function animeAvatar(seed: string): string {
  return createAvatar(lorelei, {
    seed,
    backgroundColor: ["c0aede", "b6e3f4", "d1d4f9", "ffd5dc", "ffdfbf"],
    backgroundType: ["gradientLinear"],
  }).toDataUri();
}
