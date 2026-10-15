/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 15 October 2026
 */
import { useEffect, useState } from "react";

/** `value`, once it has stopped changing for `ms` (search boxes: one request per pause,
 *  not one per keystroke). */
export function useDebounced<T>(value: T, ms = 250): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return settled;
}
