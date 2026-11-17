import { useEffect, useState } from "react";

let peaks: Record<string, number> = {};
const listeners = new Set<(value: Record<string, number>) => void>();

export function publishLanePeaks(next: Record<string, number>) {
  peaks = next;
  listeners.forEach((listener) => listener(next));
}

export function useLanePeaks() {
  const [value, setValue] = useState(peaks);
  useEffect(() => {
    const listener = (next: Record<string, number>) => setValue(next);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);
  return value;
}
