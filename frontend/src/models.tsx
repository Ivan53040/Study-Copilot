// Picking the chat model: local (LM Studio), your Claude or ChatGPT
// subscription (through Claude Code / Codex on this computer), or an API key.
// The choice is shared by every chat on the page and remembered per browser.

import { type KeyboardEvent, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { api } from "./api";
import { useDismiss } from "./components";
import { Icon } from "./icons";
import type { ModelChoice, ModelOption, ModelOptions } from "./types";

const STORAGE_KEY = "study-copilot-model";

export const sameChoice = (a: ModelChoice, b: ModelChoice) =>
  a.provider === b.provider && a.model === b.model;

/* ---- the picked model ------------------------------------------------------ */

function readChoice(): ModelChoice | null {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
    return value && typeof value.provider === "string" && typeof value.model === "string"
      ? { provider: value.provider, model: value.model }
      : null;
  } catch {
    return null;
  }
}

let picked: ModelChoice | null = readChoice();
const choiceListeners = new Set<() => void>();

export function setModelChoice(next: ModelChoice | null) {
  picked = next;
  try {
    if (next) localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable: keep it for this session */
  }
  choiceListeners.forEach((listener) => listener());
}

export function useModelChoice(): ModelChoice | null {
  return useSyncExternalStore(
    (listener) => {
      choiceListeners.add(listener);
      return () => choiceListeners.delete(listener);
    },
    () => picked,
  );
}

/* ---- what can be picked ------------------------------------------------------ */

let options: ModelOptions | null = null;
let loading: Promise<ModelOptions> | null = null;
const optionListeners = new Set<() => void>();

/** Fetch the model list (once; ``refresh`` checks the subscriptions again). */
export function loadModelOptions(refresh = false): Promise<ModelOptions> {
  if (loading && !refresh) return loading;
  if (options && !refresh) return Promise.resolve(options);
  const request = api.modelOptions(refresh).then((result) => {
    options = result;
    optionListeners.forEach((listener) => listener());
    return result;
  });
  loading = request;
  request.catch(() => undefined).finally(() => {
    if (loading === request) loading = null;
  });
  return request;
}

export function useModelOptions() {
  const current = useSyncExternalStore(
    (listener) => {
      optionListeners.add(listener);
      return () => optionListeners.delete(listener);
    },
    () => options,
  );
  const [refreshing, setRefreshing] = useState(false);
  // The list couldn't be fetched (the app is restarting, or is an older build).
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    loadModelOptions().then(
      () => setFailed(false),
      () => setFailed(true),
    );
  }, []);
  const refresh = () => {
    setRefreshing(true);
    loadModelOptions(true)
      .then(
        () => setFailed(false),
        () => setFailed(true),
      )
      .finally(() => setRefreshing(false));
  };
  return { options: current, refreshing, refresh, failed };
}

/** The picked model if it can still be picked, else null (= the default). */
export function effectiveChoice(
  list: ModelOptions | null,
  choice: ModelChoice | null,
): ModelChoice | null {
  if (!choice) return null;
  if (!list) return choice; // not loaded yet: trust what was picked
  return list.options.some((option) => sameChoice(option, choice)) ? choice : null;
}

function shownOption(list: ModelOptions | null, choice: ModelChoice | null): ModelOption | null {
  if (!list) return null;
  const wanted = effectiveChoice(list, choice) ?? list.default;
  return list.options.find((option) => sameChoice(option, wanted)) ?? null;
}

/* ---- the menu in the chat box -------------------------------------------------- */

export function ModelMenu({ onSetup }: { onSetup?: () => void }) {
  const choice = useModelChoice();
  const { options: list, refreshing, refresh, failed } = useModelOptions();
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  useDismiss(open, () => setOpen(false), [wrap]);

  const enabledItems = () =>
    Array.from(pop.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);
  // Opening puts the keyboard on the current model (or the first one).
  const loaded = Boolean(list);
  useEffect(() => {
    if (!open) return;
    const items = enabledItems();
    (pop.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]') ?? items[0])?.focus();
  }, [open, loaded]);
  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  };
  const onMenuKey = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      close(true);
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const items = enabledItems();
    if (!items.length) return;
    event.preventDefault();
    const at = items.indexOf(document.activeElement as HTMLButtonElement);
    const next =
      event.key === "Home" ? 0
      : event.key === "End" ? items.length - 1
      : event.key === "ArrowDown" ? (at + 1) % items.length
      : (at - 1 + items.length) % items.length;
    items[next].focus();
  };

  const current = shownOption(list, choice);
  const label = current?.label ?? (list ? "Default model" : "Model");
  const groups: [string, ModelOption[]][] = [];
  for (const option of list?.options ?? []) {
    const group = groups.find(([name]) => name === option.group);
    if (group) group[1].push(option);
    else groups.push([option.group, [option]]);
  }

  return (
    <div className="menu-wrap model-menu" ref={wrap}>
      <button
        type="button"
        ref={trigger}
        className={`model-btn${open ? " open" : ""}${current && !current.available ? " unavailable" : ""}`}
        title={current && !current.available && current.note ? `${current.label}: ${current.note}` : "Choose the model"}
        aria-label={`Model: ${label}${current && !current.available && current.note ? ` (${current.note})` : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="model-btn-label">{label}</span>
        <Icon name="chevron-down" size={13} />
      </button>
      {open && (
        <div
          ref={pop}
          className="popover composer-pop right model-pop"
          role="menu"
          aria-label="Choose the model"
          onKeyDown={onMenuKey}
        >
          {!list ? (
            <div className="popover-empty">
              {failed ? "Couldn’t check which models are ready. Is the app up to date?" : "Checking which models are ready…"}
            </div>
          ) : (
            groups.map(([group, items]) => (
              <div key={group} role="group" aria-label={group}>
                <div className="popover-label">{group}</div>
                {items.map((option) => {
                  const selected = current ? sameChoice(option, current) : false;
                  const isDefault = sameChoice(option, list.default);
                  return (
                    <button
                      type="button"
                      role="menuitemradio"
                      aria-checked={selected}
                      key={`${option.provider}:${option.model}`}
                      className="popover-item model-item"
                      disabled={!option.available}
                      onClick={() => {
                        setModelChoice({ provider: option.provider, model: option.model });
                        close(true);
                      }}
                    >
                      <span className="grow">
                        {option.label}
                        {isDefault && <small> · default</small>}
                      </span>
                      {option.note ? (
                        <small className="model-note">{option.note}</small>
                      ) : selected ? (
                        <span className="check"><Icon name="check" size={15} /></span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            ))
          )}
          <div className="popover-sep" />
          <button type="button" role="menuitem" className="popover-item" onClick={refresh} disabled={refreshing}>
            <Icon name="refresh-cw" size={14} />
            <span className="grow">{refreshing ? "Checking…" : "Check again"}</span>
          </button>
          {onSetup && (
            <button
              type="button"
              role="menuitem"
              className="popover-item"
              onClick={() => {
                setOpen(false);
                onSetup();
              }}
            >
              <Icon name="settings" size={14} />
              <span className="grow">Set up Claude or ChatGPT…</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
