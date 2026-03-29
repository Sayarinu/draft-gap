"use client";

import type { Dispatch, SetStateAction } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

interface UsePollingResourceOptions<T> {
  enabled?: boolean;
  intervalMs: number;
  initialData: T;
  fetcher: () => Promise<T>;
  deps?: readonly unknown[];
  formatError?: (error: unknown) => string;
}

interface UsePollingResourceResult<T> {
  data: T;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  setData: Dispatch<SetStateAction<T>>;
}

export function usePollingResource<T>({
  enabled = true,
  intervalMs,
  initialData,
  fetcher,
  deps = [],
  formatError,
}: UsePollingResourceOptions<T>): UsePollingResourceResult<T> {
  const [data, setData] = useState<T>(initialData);
  const [loading, setLoading] = useState<boolean>(enabled);
  const [error, setError] = useState<string | null>(null);
  const fetcherRef = useRef(fetcher);
  const formatErrorRef = useRef(formatError);

  fetcherRef.current = fetcher;
  formatErrorRef.current = formatError;

  const run = useCallback(async () => {
    try {
      const next = await fetcherRef.current();
      setData(next);
      setError(null);
    } catch (error) {
      const formatter = formatErrorRef.current;
      setError(formatter ? formatter(error) : error instanceof Error ? error.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    setLoading(true);
    void run();
    const id = window.setInterval(() => {
      void run();
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [deps, enabled, intervalMs, run]);

  return {
    data,
    loading,
    error,
    refresh: async () => {
      await run();
    },
    setData,
  };
}
