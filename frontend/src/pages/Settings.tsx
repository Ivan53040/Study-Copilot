import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import type { AppSettings, Job } from "../types";
import { Icon } from "../icons";
import {
  type Appearance,
  type ThemeMode,
  DEFAULT_APPEARANCE,
  PALETTES,
  applyAppearance,
  loadAppearance,
  resolveTheme,
  saveAppearance,
} from "../theme";

const THEME_OPTIONS: { id: ThemeMode; label: string; icon: string }[] = [
  { id: "light", label: "Light", icon: "sun" },
  { id: "dark", label: "Dark", icon: "moon" },
  { id: "system", label: "Match system", icon: "monitor" },
];

/** Inline colours for the Light / Dark / System previews, in the chosen palette. */
function modePreview(paletteId: string, mode: ThemeMode) {
  const palette = PALETTES.find((item) => item.id === paletteId) ?? PALETTES[0];
  const split = (a: string, b: string) => `linear-gradient(135deg, ${a} 50%, ${b} 50%)`;
  if (mode === "system") {
    const { light, dark } = palette;
    return {
      thumb: { background: split(light.bg, dark.bg) },
      side: { background: split(light.sidebar, dark.sidebar) },
      main: { background: "transparent" },
      bubble: { background: split(light.panel, dark.panel) },
    };
  }
  const swatch = palette[mode];
  return {
    thumb: {},
    side: { background: swatch.sidebar },
    main: { background: swatch.bg },
    bubble: { background: swatch.panel },
  };
}

const TASK_MODEL_LABELS: Array<[keyof AppSettings["task_models"], string]> = [
  ["chat", "Chat"],
  ["visual_pages", "Visual page indexing"],
  ["deep_ask", "Deep ask"],
  ["transformations", "Transformations"],
  ["quiz_marking", "Quiz marking"],
  ["translation", "Translation"],
  ["voice_notes", "Voice notes"],
];

export function SettingsPage({
  onSaved,
  onAppearanceChange,
}: {
  onSaved: () => void;
  onAppearanceChange?: (value: Appearance) => void;
}) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [appearance, setAppearance] = useState(loadAppearance);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [visualJob, setVisualJob] = useState<Job | null>(null);
  // Write-only: typed here, sent on save, never returned by the backend.
  const [apiKey, setApiKey] = useState("");

  const chooseLecturesFolder = async () => {
    setMessage("");
    try {
      if (!("__TAURI_INTERNALS__" in window)) {
        setMessage("Folder browsing is available in the desktop app.");
        return;
      }
      const { open } = await import("@tauri-apps/plugin-dialog");
      const selected = await open({
        directory: true,
        multiple: false,
        title: "Choose your Lecture Notes folder",
      });
      if (typeof selected === "string") {
        setSettings((current) =>
          current ? { ...current, lectures_root: selected, lectures_root_exists: true } : current,
        );
      }
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  const clearLecturesFolder = () =>
    setSettings((current) =>
      current ? { ...current, lectures_root: null, lectures_root_exists: null } : current,
    );

  const chooseVault = async () => {
    setMessage("");
    try {
      if (!("__TAURI_INTERNALS__" in window)) {
        setMessage("Folder browsing is available in the desktop app.");
        return;
      }
      const { open } = await import("@tauri-apps/plugin-dialog");
      const selected = await open({
        directory: true,
        multiple: false,
        title: "Choose your Study Vault",
      });
      if (typeof selected === "string") {
        setSettings((current) =>
          current ? { ...current, vault_root: selected, vault_exists: true } : current,
        );
      }
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  useEffect(() => {
    api.settings().then(setSettings).catch((e) => setMessage((e as Error).message));
  }, []);

  useEffect(() => {
    if (!visualJob || !["queued", "running"].includes(visualJob.status)) return;
    const timer = window.setTimeout(() => {
      api.job(visualJob.id).then(setVisualJob).catch((e) => setMessage((e as Error).message));
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [visualJob]);

  const indexVisualPages = async () => {
    try {
      setVisualJob(await api.createJob("visual_pages_index", { limit: 20 }));
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  const updateAppearance = (next: Appearance) => {
    setAppearance(next);
    applyAppearance(next);
    saveAppearance(next);
    onAppearanceChange?.(next);
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!settings) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await api.saveSettings({
        vault_root: settings.vault_root,
        lectures_root: settings.lectures_root,
        default_provider: settings.default_provider,
        llm_base_url: settings.llm_base_url,
        llm_model: settings.llm_model,
        openai_base_url: settings.openai_base_url,
        openai_model: settings.openai_model,
        anthropic_model: settings.anthropic_model,
        api_key: apiKey.trim() || null,
        embedding_provider: settings.embedding_provider,
        embedding_base_url: settings.embedding_base_url,
        embedding_model: settings.embedding_model,
        task_models: settings.task_models,
        chunk_tokens: settings.chunk_tokens,
        chunk_overlap_tokens: settings.chunk_overlap_tokens,
        min_chunk_tokens: settings.min_chunk_tokens,
        temperature: settings.temperature,
        require_citations: settings.require_citations,
        include_page_images: settings.include_page_images,
      });
      setSettings(result.settings);
      setApiKey("");
      setMessage("Settings saved. Indexing the whole vault…");
      const scan = await api.scanVault();
      setMessage(
        `Settings saved. Vault indexed: ${scan.new} new, ${scan.updated} updated, ${scan.unchanged} unchanged.`,
      );
      onSaved();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const testConnection = async () => {
    if (!settings) return;
    setBusy(true);
    setMessage("Testing connection…");
    try {
      const result = await api.testLlm(settings.llm_base_url, settings.llm_model);
      setMessage(
        result.model_available === false
          ? `Connected, but “${settings.llm_model}” is not loaded. Available: ${result.models.join(", ") || "none"}`
          : "LLM connection successful.",
      );
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const updateTaskModel = (
    task: keyof AppSettings["task_models"],
    patch: Partial<AppSettings["task_models"][typeof task]>,
  ) => {
    if (!settings) return;
    setSettings({
      ...settings,
      task_models: {
        ...settings.task_models,
        [task]: { ...settings.task_models[task], ...patch },
      },
    });
  };

  if (!settings) {
    return <div className="spinner">{message || "Loading settings…"}</div>;
  }
  const visualSummary = visualJob?.result?.visual_pages as
    | { indexed: number; skipped: number; errors: string[] }
    | undefined;

  return (
    <form className="settings-page" onSubmit={save}>
      <h1 className="page-title">Settings</h1>

      <p className="page-sub">Choose your vault, wire up your local model, and make the workspace yours.</p>

      <section className="settings-section card">
        <div>
          <h2>Vault</h2>
          <p className="muted">The Obsidian vault Study Copilot reads and writes.</p>
        </div>
        <label className="field field-wide">
          <span>Vault folder</span>
          <div className="path-picker">
            <input value={settings.vault_root} readOnly />
            <button type="button" onClick={chooseVault}>Choose folder…</button>
          </div>
          <small className={settings.vault_exists ? "good-text" : "danger-text"}>
            {settings.vault_exists ? "Current folder found" : "Current folder is missing"}
          </small>
        </label>
      </section>

      <section className="settings-section card">
        <div>
          <h2>Lecture Notes</h2>
          <p className="muted">
            The folder containing your lecture PDFs and PowerPoint slides. Leave blank to use
            <code> Vault/Lecture Materials</code> by default.
          </p>
        </div>
        <label className="field field-wide">
          <span>Lecture notes folder</span>
          <div className="path-picker">
            <input value={settings.lectures_root ?? ""} readOnly placeholder="Using vault/Lecture Materials (default)" />
            <button type="button" onClick={chooseLecturesFolder}>Choose folder…</button>
            {settings.lectures_root && (
              <button type="button" onClick={clearLecturesFolder}>Clear</button>
            )}
          </div>
          {settings.lectures_root && (
            <small className={settings.lectures_root_exists ? "good-text" : "danger-text"}>
              {settings.lectures_root_exists ? "Folder found" : "Folder not found"}
            </small>
          )}
        </label>
      </section>

      <section className="settings-section card">
        <div>
          <h2>Language model</h2>
          <p className="muted">
            Run a local model with LM Studio, or use a cloud provider (OpenAI or Claude).
            Cloud keys are stored in a local <code>.env</code> file, never in the synced config.
          </p>
        </div>
        <div className="settings-grid">
          <label className="field">
            <span>Provider</span>
            <select
              value={settings.default_provider}
              onChange={(e) => setSettings({ ...settings, default_provider: e.target.value as AppSettings["default_provider"] })}
            >
              <option value="lmstudio">LM Studio (local)</option>
              <option value="openai">OpenAI (GPT)</option>
              <option value="anthropic">Anthropic (Claude)</option>
              <option value="echo">Offline echo (testing)</option>
            </select>
          </label>

          {settings.default_provider === "lmstudio" && (
            <>
              <label className="field">
                <span>Model</span>
                <input value={settings.llm_model} onChange={(e) => setSettings({ ...settings, llm_model: e.target.value })} />
              </label>
              <label className="field field-wide">
                <span>Base URL</span>
                <input value={settings.llm_base_url} onChange={(e) => setSettings({ ...settings, llm_base_url: e.target.value })} />
              </label>
            </>
          )}

          {settings.default_provider === "openai" && (
            <>
              <label className="field">
                <span>Model</span>
                <input value={settings.openai_model} onChange={(e) => setSettings({ ...settings, openai_model: e.target.value })} placeholder="gpt-4o-mini" />
              </label>
              <label className="field field-wide">
                <span>Base URL</span>
                <input value={settings.openai_base_url} onChange={(e) => setSettings({ ...settings, openai_base_url: e.target.value })} placeholder="https://api.openai.com/v1" />
              </label>
              <label className="field field-wide">
                <span>API key</span>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={settings.openai_key_set ? "Key saved — leave blank to keep it" : "Paste your OpenAI API key"}
                />
                <small className={settings.openai_key_set ? "good-text" : "muted"}>
                  {settings.openai_key_set ? "A key is saved for OpenAI." : "No key saved yet — required for cloud calls."}
                </small>
              </label>
            </>
          )}

          {settings.default_provider === "anthropic" && (
            <>
              <label className="field">
                <span>Model</span>
                <input value={settings.anthropic_model} onChange={(e) => setSettings({ ...settings, anthropic_model: e.target.value })} placeholder="claude-opus-4-8" />
              </label>
              <label className="field field-wide">
                <span>API key</span>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={settings.anthropic_key_set ? "Key saved — leave blank to keep it" : "Paste your Anthropic API key"}
                />
                <small className={settings.anthropic_key_set ? "good-text" : "muted"}>
                  {settings.anthropic_key_set ? "A key is saved for Claude." : "No key saved yet — required for cloud calls. Run `pip install anthropic` once."}
                </small>
              </label>
            </>
          )}

          {settings.default_provider !== "echo" && (
            <label className="field">
              <span>Temperature</span>
              <input type="number" min="0" max="2" step="0.1" value={settings.temperature} onChange={(e) => setSettings({ ...settings, temperature: Number(e.target.value) })} />
            </label>
          )}
          <label className="check-field">
            <input type="checkbox" checked={settings.require_citations} onChange={(e) => setSettings({ ...settings, require_citations: e.target.checked })} />
            Require source citations
          </label>
          <label className="check-field">
            <input type="checkbox" checked={settings.include_page_images} onChange={(e) => setSettings({ ...settings, include_page_images: e.target.checked })} />
            Send retrieved page images to the chat model
          </label>
          {settings.default_provider === "lmstudio" && (
            <button type="button" onClick={testConnection} disabled={busy}>
              Test connection
            </button>
          )}
        </div>
      </section>

      <section className="settings-section card">
        <div>
          <h2>Task models</h2>
          <p className="muted">Leave a task blank to use the default provider above.</p>
        </div>
        <div className="task-model-table">
          {TASK_MODEL_LABELS.map(([task, label]) => {
            const override = settings.task_models[task];
            return (
              <div className="task-model-row" key={task}>
                <span>{label}</span>
                <select
                  value={override.provider ?? ""}
                  onChange={(event) =>
                    updateTaskModel(task, {
                      provider: event.target.value
                        ? (event.target.value as AppSettings["default_provider"])
                        : null,
                    })
                  }
                >
                  <option value="">Default</option>
                  <option value="lmstudio">LM Studio</option>
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="echo">Echo</option>
                </select>
                <input
                  value={override.model ?? ""}
                  onChange={(event) => updateTaskModel(task, { model: event.target.value || null })}
                  placeholder="Model override"
                />
                <input
                  value={override.base_url ?? ""}
                  onChange={(event) =>
                    updateTaskModel(task, { base_url: event.target.value || null })
                  }
                  placeholder="Base URL override"
                />
              </div>
            );
          })}
        </div>
      </section>

      <section className="settings-section card">
        <div>
          <h2>Visual pages</h2>
          <p className="muted">Save a vision-capable task model above, then describe the next 20 PDF pages or PowerPoint slides for search.</p>
        </div>
        <div>
          <button type="button" onClick={indexVisualPages} disabled={busy || visualJob?.status === "queued" || visualJob?.status === "running"}>Index next 20 pages</button>
          {visualJob && <p className="muted">{visualJob.status}: {visualJob.error ?? visualJob.message ?? ""}</p>}
          {visualSummary && <p className="muted">{visualSummary.indexed} pages indexed, {visualSummary.skipped} already indexed, {visualSummary.errors.length} errors.</p>}
        </div>
      </section>

      <section className="settings-section card">
        <div>
          <h2>Chunking</h2>
          <p className="muted">Approximate token budgets for newly indexed material.</p>
        </div>
        <div className="settings-grid">
          <label className="field">
            <span>Chunk tokens</span>
            <input
              type="number"
              min="80"
              value={settings.chunk_tokens}
              onChange={(event) =>
                setSettings({ ...settings, chunk_tokens: Number(event.target.value) })
              }
            />
          </label>
          <label className="field">
            <span>Overlap tokens</span>
            <input
              type="number"
              min="0"
              value={settings.chunk_overlap_tokens}
              onChange={(event) =>
                setSettings({ ...settings, chunk_overlap_tokens: Number(event.target.value) })
              }
            />
          </label>
          <label className="field">
            <span>Minimum tokens</span>
            <input
              type="number"
              min="1"
              value={settings.min_chunk_tokens}
              onChange={(event) =>
                setSettings({ ...settings, min_chunk_tokens: Number(event.target.value) })
              }
            />
          </label>
        </div>
      </section>

      <section className="settings-section card">
        <div>
          <h2>Embeddings</h2>
          <p className="muted">Used for semantic search. Hash mode works fully offline.</p>
        </div>
        <div className="settings-grid">
          <label className="field">
            <span>Provider</span>
            <select value={settings.embedding_provider} onChange={(e) => setSettings({ ...settings, embedding_provider: e.target.value as AppSettings["embedding_provider"] })}>
              <option value="lmstudio">LM Studio / OpenAI compatible</option>
              <option value="hash">Offline hash</option>
            </select>
          </label>
          <label className="field">
            <span>Model</span>
            <input value={settings.embedding_model} onChange={(e) => setSettings({ ...settings, embedding_model: e.target.value })} />
          </label>
          <label className="field field-wide">
            <span>Base URL override (optional)</span>
            <input value={settings.embedding_base_url ?? ""} onChange={(e) => setSettings({ ...settings, embedding_base_url: e.target.value || null })} placeholder="Uses the LLM base URL when empty" />
          </label>
        </div>
      </section>

      <section className="settings-section card">
        <div>
          <h2>Appearance</h2>
          <p className="muted">Colour theme, light or dark, reading font and text size. Saved on this device.</p>
        </div>
        <div className="appearance-controls">
          <div className="field">
            <span>Colour theme</span>
            <div className="palette-cards" role="radiogroup" aria-label="Colour theme">
              {PALETTES.map((palette) => {
                const swatch = palette[resolveTheme(appearance.theme)];
                const active = appearance.palette === palette.id;
                return (
                  <button
                    type="button"
                    key={palette.id}
                    role="radio"
                    aria-checked={active}
                    className={`palette-card${active ? " active" : ""}`}
                    onClick={() => updateAppearance({ ...appearance, palette: palette.id })}
                  >
                    <span className="palette-preview" style={{ background: swatch.bg }}>
                      <i className="pp-side" style={{ background: swatch.sidebar }} />
                      <i className="pp-main">
                        <i className="pp-bubble" style={{ background: swatch["user-bubble"] }} />
                        <i className="pp-card" style={{ background: swatch.panel }}>
                          <i className="pp-dot" style={{ background: swatch.accent }} />
                        </i>
                      </i>
                    </span>
                    <span className="palette-label">
                      <b>{palette.label}</b>
                      <small>{palette.note}</small>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
          <div className="field">
            <span>Mode</span>
            <div className="theme-cards">
              {THEME_OPTIONS.map((option) => (
                <button
                  type="button"
                  key={option.id}
                  className={`theme-card${appearance.theme === option.id ? " active" : ""}`}
                  aria-pressed={appearance.theme === option.id}
                  onClick={() => updateAppearance({ ...appearance, theme: option.id })}
                >
                  <span className={`theme-thumb ${option.id}`} style={modePreview(appearance.palette, option.id).thumb}>
                    <i className="tt-side" style={modePreview(appearance.palette, option.id).side} />
                    <i className="tt-main" style={modePreview(appearance.palette, option.id).main}>
                      <i className="tt-bubble" style={modePreview(appearance.palette, option.id).bubble} />
                    </i>
                  </span>
                  <span className="theme-label"><Icon name={option.icon} size={14} />{option.label}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="field">
            <span>Reading font</span>
            <div className="font-cards">
              {([
                ["serif", "Serif", "Calm, book-like answers and notes", "var(--font-serif)"],
                ["sans", "Sans", "Matches the interface font", "var(--font-sans)"],
              ] as const).map(([id, label, hint, family]) => (
                <button
                  type="button"
                  key={id}
                  className={`font-card${appearance.readingFont === id ? " active" : ""}`}
                  aria-pressed={appearance.readingFont === id}
                  onClick={() => updateAppearance({ ...appearance, readingFont: id })}
                >
                  <b style={{ fontFamily: family }}>Aa</b>
                  <span>{label}</span>
                  <small>{hint}</small>
                </button>
              ))}
            </div>
          </div>
          <label className="field font-size-field">
            <span>Text size · {appearance.fontSize}px</span>
            <input
              type="range"
              min="12"
              max="20"
              step="1"
              value={appearance.fontSize}
              onChange={(event) =>
                updateAppearance({ ...appearance, fontSize: Number(event.target.value) })
              }
            />
          </label>
          <label className="field">
            <span>What should Study Copilot call you?</span>
            <input
              value={appearance.name}
              maxLength={40}
              placeholder="Used in the greeting on a new chat"
              onChange={(event) => updateAppearance({ ...appearance, name: event.target.value })}
              onKeyDown={(event) => {
                // Saved instantly; Enter must not submit (and re-index) the settings form.
                if (event.key === "Enter") event.preventDefault();
              }}
            />
          </label>
          <div>
            <button type="button" onClick={() => updateAppearance({ ...DEFAULT_APPEARANCE, name: appearance.name })}>Reset appearance</button>
          </div>
        </div>
      </section>

      <div className="settings-actions">
        <span className={message.startsWith("4") ? "danger-text" : "muted"}>{message}</span>
        <button className="primary" type="submit" disabled={busy}>{busy ? "Working…" : "Save settings"}</button>
      </div>
    </form>
  );
}
