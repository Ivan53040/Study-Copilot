// Reading-view translation: Ctrl/⌘-hover a word for a tooltip, right-click a
// selection for "Translate to Traditional Chinese". useSelectionTranslation
// holds the state and handlers; TranslationOverlays draws the bubbles.

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { Icon } from "../../icons";
import { clamp } from "./paths";
import {
  normalizeTranslationText,
  selectedTextIn,
  wordAtPoint,
  type TranslationBubble,
  type TranslationMenu,
} from "./translation";

export function useSelectionTranslation({ onMenuOpen }: { onMenuOpen?: () => void } = {}) {
  const translationCache = useRef<Map<string, string>>(new Map());
  const hoverTranslationTimer = useRef<number | null>(null);
  const hoverTranslationRequest = useRef(0);
  const popupTranslationRequest = useRef(0);
  const onMenuOpenRef = useRef(onMenuOpen);
  onMenuOpenRef.current = onMenuOpen;
  const [tooltip, setTooltip] = useState<TranslationBubble | null>(null);
  const [menu, setMenu] = useState<TranslationMenu | null>(null);
  const [popup, setPopup] = useState<TranslationBubble | null>(null);

  const translateText = useCallback(async (rawText: string) => {
    const text = normalizeTranslationText(rawText);
    const cached = translationCache.current.get(text);
    if (cached) return cached;
    const result = await api.translateNoteText({ text });
    translationCache.current.set(text, result.translation);
    return result.translation;
  }, []);

  const clearHover = useCallback(() => {
    if (hoverTranslationTimer.current !== null) {
      window.clearTimeout(hoverTranslationTimer.current);
      hoverTranslationTimer.current = null;
    }
    hoverTranslationRequest.current += 1;
    setTooltip(null);
  }, []);

  useEffect(() => {
    return () => {
      if (hoverTranslationTimer.current !== null) {
        window.clearTimeout(hoverTranslationTimer.current);
      }
    };
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenu(null);
        setPopup(null);
        clearHover();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [clearHover]);

  const onHover = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!(event.ctrlKey || event.metaKey)) {
        clearHover();
        return;
      }
      const word = wordAtPoint(event, event.currentTarget);
      if (!word) {
        clearHover();
        return;
      }
      const x = clamp(event.clientX + 14, 8, window.innerWidth - 328);
      const y = clamp(event.clientY + 18, 8, window.innerHeight - 170);
      if (tooltip?.text === word && tooltip.status !== "error") {
        setTooltip((current) => (current ? { ...current, x, y } : current));
        return;
      }
      if (hoverTranslationTimer.current !== null) {
        window.clearTimeout(hoverTranslationTimer.current);
      }
      const requestId = ++hoverTranslationRequest.current;
      const cached = translationCache.current.get(word);
      if (cached) {
        setTooltip({ text: word, translation: cached, status: "ready", x, y });
        return;
      }
      setTooltip({ text: word, translation: null, status: "loading", x, y });
      hoverTranslationTimer.current = window.setTimeout(() => {
        void translateText(word)
          .then((translation) => {
            if (hoverTranslationRequest.current === requestId) {
              setTooltip({ text: word, translation, status: "ready", x, y });
            }
          })
          .catch((error) => {
            if (hoverTranslationRequest.current === requestId) {
              setTooltip({
                text: word,
                translation: null,
                status: "error",
                error: (error as Error).message,
                x,
                y,
              });
            }
          });
      }, 250);
    },
    [clearHover, translateText, tooltip],
  );

  const onContextMenu = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      const text = selectedTextIn(event.currentTarget);
      if (!text) {
        setMenu(null);
        return;
      }
      event.preventDefault();
      onMenuOpenRef.current?.();
      clearHover();
      setMenu({
        text,
        x: clamp(event.clientX, 8, window.innerWidth - 250),
        y: clamp(event.clientY, 8, window.innerHeight - 70),
      });
    },
    [clearHover],
  );

  const openPopup = useCallback(
    (item: TranslationMenu) => {
      const x = clamp(item.x, 8, window.innerWidth - 390);
      const y = clamp(item.y, 8, window.innerHeight - 340);
      const cached = translationCache.current.get(item.text);
      setMenu(null);
      setPopup({
        text: item.text,
        translation: cached ?? null,
        status: cached ? "ready" : "loading",
        x,
        y,
      });
      if (cached) return;
      const requestId = ++popupTranslationRequest.current;
      void translateText(item.text)
        .then((translation) => {
          if (popupTranslationRequest.current === requestId) {
            setPopup({ text: item.text, translation, status: "ready", x, y });
          }
        })
        .catch((error) => {
          if (popupTranslationRequest.current === requestId) {
            setPopup({
              text: item.text,
              translation: null,
              status: "error",
              error: (error as Error).message,
              x,
              y,
            });
          }
        });
    },
    [translateText],
  );

  /** Close every bubble (e.g. before translating the whole note). */
  const closeAll = useCallback(() => {
    setMenu(null);
    setPopup(null);
    clearHover();
  }, [clearHover]);

  return {
    tooltip,
    menu,
    popup,
    setMenu,
    setPopup,
    onHover,
    onContextMenu,
    clearHover,
    openPopup,
    closeAll,
  };
}

export type SelectionTranslation = ReturnType<typeof useSelectionTranslation>;

export function TranslationOverlays({
  translation,
  onCopied,
}: {
  translation: SelectionTranslation;
  onCopied: () => void;
}) {
  const { tooltip, menu, popup, setMenu, setPopup, openPopup } = translation;
  return (
    <>
      {tooltip && (
        <div
          className={`translation-tooltip ${tooltip.status}`}
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          <div className="translation-source">{tooltip.text}</div>
          <div className="translation-result">
            {tooltip.status === "loading"
              ? "Translating..."
              : tooltip.status === "error"
                ? tooltip.error
                : tooltip.translation}
          </div>
        </div>
      )}
      {menu && (
        <>
          <div className="menu-backdrop" onClick={() => setMenu(null)} />
          <div
            className="more-menu context-menu translation-context-menu"
            style={{ left: menu.x, top: menu.y }}
          >
            <button className="more-item" onClick={() => openPopup(menu)}>
              <Icon name="sparkles" size={15} /> Translate to Traditional Chinese
            </button>
          </div>
        </>
      )}
      {popup && (
        <>
          <div className="menu-backdrop translation-popup-backdrop" onClick={() => setPopup(null)} />
          <div
            className={`translation-popup ${popup.status}`}
            style={{ left: popup.x, top: popup.y }}
          >
            <div className="translation-popup-header">
              <div>
                <div className="small muted">English to Traditional Chinese</div>
                <strong>Translation</strong>
              </div>
              <button className="icon-btn" title="Close" onClick={() => setPopup(null)}>×</button>
            </div>
            <div className="translation-popup-section">
              <div className="small muted">Original</div>
              <div className="translation-original">{popup.text}</div>
            </div>
            <div className="translation-popup-section">
              <div className="small muted">Traditional Chinese</div>
              <div className="translation-output">
                {popup.status === "loading"
                  ? popup.translation ?? "Translating..."
                  : popup.status === "error"
                    ? popup.error
                    : popup.translation}
              </div>
            </div>
            <div className="translation-popup-actions">
              <button
                disabled={!popup.translation}
                onClick={() => {
                  if (popup.translation) {
                    void navigator.clipboard.writeText(popup.translation);
                    onCopied();
                  }
                }}
              >
                <Icon name="copy" size={14} /> Copy
              </button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
