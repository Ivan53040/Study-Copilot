// State hooks for the notes workspace: settings remembered in localStorage,
// resizable side panels, and the open tabs.

import { useCallback, useEffect, useRef, useState } from "react";
import { clamp } from "./paths";

/** useState that is read from and written back to localStorage[key]. */
export function useStoredState<T>(
  key: string,
  read: (raw: string | null) => T,
  write: (value: T) => string,
) {
  const [value, setValue] = useState<T>(() => read(localStorage.getItem(key)));
  // `write` is expected to be a stable formatter, so it isn't a dependency.
  useEffect(() => localStorage.setItem(key, write(value)), [key, value]);
  return [value, setValue] as const;
}

/** A Set of strings stored as a JSON array. */
export function useStoredSet(key: string) {
  return useStoredState<Set<string>>(
    key,
    (raw) => {
      try {
        return new Set(JSON.parse(raw ?? "[]"));
      } catch {
        return new Set();
      }
    },
    (value) => JSON.stringify([...value]),
  );
}

/** A number stored as text; `fallback` when missing, zero or not a number. */
export function useStoredNumber(key: string, fallback: number) {
  return useStoredState<number>(key, (raw) => Number(raw) || fallback, String);
}

/** Widths of the file tree and outline panels, resizable by dragging. */
export function usePanelWidths() {
  const [treeWidth, setTreeWidth] = useStoredNumber("ws.treeWidth", 240);
  const [tocWidth, setTocWidth] = useStoredNumber("ws.tocWidth", 240);

  const startResize = (e: React.MouseEvent, side: "tree" | "toc") => {
    e.preventDefault();
    const startX = e.clientX;
    const startTree = treeWidth;
    const startToc = tocWidth;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    const onMove = (ev: MouseEvent) => {
      const dx = ev.clientX - startX;
      if (side === "tree") setTreeWidth(clamp(startTree + dx, 160, 520));
      else setTocWidth(clamp(startToc - dx, 150, 480));
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  return { treeWidth, tocWidth, startResize };
}

/**
 * Open tabs and the active one. Tab ids are vault paths, or "new:N" for an
 * empty tab. A detached window (a note popped out) starts with just its note
 * and doesn't touch the main window's saved tabs.
 */
export function useNoteTabs({ detached, path }: { detached: boolean; path: string | null }) {
  const [tabs, setTabs] = useState<string[]>(() => {
    if (detached && path) return [path];
    try { return JSON.parse(localStorage.getItem("ws.tabs") ?? "[]"); }
    catch { return []; }
  });
  const [active, setActive] = useState<string | null>(
    () => detached && path ? path : localStorage.getItem("ws.active"),
  );
  const activeRef = useRef<string | null>(null);
  const newCounter = useRef(0);

  useEffect(() => {
    activeRef.current = active;
  }, [active]);
  useEffect(() => {
    if (!detached) localStorage.setItem("ws.tabs", JSON.stringify(tabs));
  }, [detached, tabs]);
  useEffect(() => {
    if (detached) return;
    if (active) localStorage.setItem("ws.active", active);
    else localStorage.removeItem("ws.active");
  }, [active, detached]);

  const openNewTab = () => {
    const id = `new:${++newCounter.current}`;
    setTabs((p) => [...p, id]);
    setActive(id);
  };

  /** Open `path` in place of the empty tab it was picked from. */
  const pickInNewTab = (picked: string) => {
    setTabs((prev) => {
      const arr = prev.filter((x) => x !== activeRef.current);
      if (!arr.includes(picked)) arr.push(picked);
      return arr;
    });
    setActive(picked);
  };

  /** Focus `p` if open; else open it in a new tab or in place of the active one. */
  const openInTab = useCallback((p: string, newTab: boolean) => {
    setTabs((prev) => {
      if (prev.includes(p)) return prev;
      if (newTab || !activeRef.current) return [...prev, p];
      return prev.map((x) => (x === activeRef.current ? p : x));
    });
    setActive(p);
  }, []);

  const closeTab = useCallback((p: string) => {
    setTabs((prev) => {
      const idx = prev.indexOf(p);
      const next = prev.filter((x) => x !== p);
      if (activeRef.current === p) {
        const fallback = next[idx] ?? next[idx - 1] ?? next[next.length - 1] ?? null;
        setActive(fallback);
      }
      return next;
    });
  }, []);

  return {
    tabs,
    setTabs,
    active,
    setActive,
    activeRef,
    openNewTab,
    pickInNewTab,
    openInTab,
    closeTab,
  };
}
