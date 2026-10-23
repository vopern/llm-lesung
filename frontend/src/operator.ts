import { useEffect, useState } from "react";
import { fetchMeta, type Meta, type Operator } from "./api";

// Server metadata; null until loaded.
export function useMeta(): Meta | null {
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchMeta()
      .then((m) => {
        if (!cancelled) setMeta(m);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);
  return meta;
}

// The operator details are server data; null until loaded, and when none are set.
export function useOperator(): Operator | null {
  return useMeta()?.operator ?? null;
}

export function hasImpressum(operator: Operator | null): operator is Operator {
  return !!operator?.name && operator.address.length > 0;
}
