"use client";
import { useCallback, useEffect, useState } from "react";
import { DEFAULT_VISIBLE_BOOKS } from "./books";

const STORAGE_KEY = "visible_books_v1";

/**
 * LocalStorage-backed set of visible sportsbook keys. SSR-safe: returns defaults
 * on the server and syncs from localStorage on mount.
 */
export function useVisibleBooks() {
  const [set, setSet] = useState<Set<string>>(() => new Set(DEFAULT_VISIBLE_BOOKS));

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as string[];
        if (Array.isArray(parsed)) setSet(new Set(parsed));
      }
    } catch {}
  }, []);

  const persist = useCallback((next: Set<string>) => {
    setSet(new Set(next));
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify([...next]));
    } catch {}
  }, []);

  const toggle = useCallback(
    (key: string) => {
      const next = new Set(set);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      persist(next);
    },
    [set, persist]
  );

  const setAll = useCallback(
    (keys: string[]) => persist(new Set(keys)),
    [persist]
  );

  return { visible: set, toggle, setAll };
}
