import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import type { AppSettings } from "../types";

export type Appearance = {
  accent: string;
  background: string;
  panel: string;
  panel2: string;
  border: string;
  text: string;
  muted: string;
  fontSize: number;
};

export const APPEARANCE_PRESETS: { name: string; description: string; colors: Appearance }[] = [
  {
    name: "Midnight",
    description: "Study Copilot blue",
    colors: {
      accent: "#6ea8fe", background: "#0f1117", panel: "#171a23",
      panel2: "#1e222e", border: "#2a2f3d", text: "#e6e8ee", muted: "#9aa3b2",
      fontSize: 14,
    },
  },
  {
    name: "Obsidian",
    description: "Charcoal and violet",
    colors: {
      accent: "#a78bfa", background: "#191919", panel: "#202020",
      panel2: "#2a2a2a", border: "#3a3a3a", text: "#dcddde", muted: "#999999",
      fontSize: 14,
    },
  },
  {
    name: "Nord",
    description: "Cool polar blue",
    colors: {
      accent: "#88c0d0", background: "#2e3440", panel: "#3b4252",
      panel2: "#434c5e", border: "#4c566a", text: "#eceff4", muted: "#b8c1d1",
      fontSize: 14,
    },
  },
  {
    name: "Forest",
    description: "Quiet deep green",
    colors: {
      accent: "#7ccf98", background: "#111a16", panel: "#18251e",
      panel2: "#213128", border: "#30483a", text: "#e4eee8", muted: "#9bb2a3",
      fontSize: 14,
    },
  },
  {
    name: "Paper",
    description: "Warm reading theme",
    colors: {
      accent: "#a05a2c", background: "#f4efe5", panel: "#fffaf0",
      panel2: "#ebe3d4", border: "#d2c6b4", text: "#302a24", muted: "#756b60",
      fontSize: 14,
    },
  },
  {
    name: "Snow",
    description: "Clean white theme",
    colors: {
      accent: "#2563eb", background: "#f5f7fb", panel: "#ffffff",
      panel2: "#edf1f7", border: "#d5dbe6", text: "#18202c", muted: "#687386",
      fontSize: 14,
    },
  },
];

const DEFAULT_APPEARANCE: Appearance = APPEARANCE_PRESETS[0].colors;

export function applyAppearance(value: Appearance) {
  const root = document.documentElement.style;
  root.setProperty("--accent", value.accent);
  root.setProperty("--accent-2", value.accent);
  root.setProperty("--bg", value.background);
  root.setProperty("--panel", value.panel);
  root.setProperty("--panel-2", value.panel2);
  root.setProperty("--border", value.border);
  root.setProperty("--text", value.text);
  root.setProperty("--muted", value.muted);
  root.setProperty("--base-font-size", `${value.fontSize}px`);
}

const LEGACY_APPEARANCE: Appearance = {
  accent: "#6ea8fe",
  background: "#0f1117",
  panel: "#171a23",
  panel2: "#1e222e",
  border: "#2a2f3d",
  text: "#e6e8ee",
  muted: "#9aa3b2",
  fontSize: 14,
};

export function loadAppearance(): Appearance {
  try {
    return {
      ...DEFAULT_APPEARANCE,
      ...LEGACY_APPEARANCE,
      ...JSON.parse(localStorage.getItem("study-copilot-appearance") ?? "{}"),
    };
  } catch {
    return DEFAULT_APPEARANCE;
  }
}

export function SettingsPage({ onSaved }: { onSaved: () => void }) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [appearance, setAppearance] = useState(loadAppearance);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

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

  const updateAppearance = (next: Appearance) => {
    setAppearance(next);
    applyAppearance(next);
    localStorage.setItem("study-copilot-appearance", JSON.stringify(next));
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
        embedding_provider: settings.embedding_provider,
        embedding_base_url: settings.embedding_base_url,
        embedding_model: settings.embedding_model,
        temperature: settings.temperature,
        require_citations: settings.require_citations,
      });
      setSettings(result.settings);
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

  if (!settings) {
    return <div className="spinner">{message || "Loading settings…"}</div>;
  }

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
          <p className="muted">OpenAI-compatible local endpoints such as LM Studio are supported.</p>
        </div>
        <div className="settings-grid">
          <label className="field">
            <span>Provider</span>
            <select
              value={settings.default_provider}
              onChange={(e) => setSettings({ ...settings, default_provider: e.target.value as AppSettings["default_provider"] })}
            >
              <option value="lmstudio">LM Studio / OpenAI compatible</option>
              <option value="echo">Offline echo (testing)</option>
            </select>
          </label>
          <label className="field">
            <span>Model</span>
            <input value={settings.llm_model} onChange={(e) => setSettings({ ...settings, llm_model: e.target.value })} />
          </label>
          <label className="field field-wide">
            <span>Base URL</span>
            <input value={settings.llm_base_url} onChange={(e) => setSettings({ ...settings, llm_base_url: e.target.value })} />
          </label>
          <label className="field">
            <span>Temperature</span>
            <input type="number" min="0" max="2" step="0.1" value={settings.temperature} onChange={(e) => setSettings({ ...settings, temperature: Number(e.target.value) })} />
          </label>
          <label className="check-field">
            <input type="checkbox" checked={settings.require_citations} onChange={(e) => setSettings({ ...settings, require_citations: e.target.checked })} />
            Require source citations
          </label>
          <button type="button" onClick={testConnection} disabled={busy || settings.default_provider === "echo"}>
            Test connection
          </button>
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
          <p className="muted">Choose a starting theme, then customise its colours and text size. Changes are saved on this device.</p>
        </div>
        <div className="appearance-controls">
          <div className="theme-presets">
            {APPEARANCE_PRESETS.map((preset) => (
              <button
                type="button"
                className="theme-preset"
                key={preset.name}
                onClick={() => updateAppearance({ ...preset.colors, fontSize: appearance.fontSize })}
                title={preset.description}
              >
                <span className="theme-swatches">
                  <i style={{ background: preset.colors.background }} />
                  <i style={{ background: preset.colors.panel }} />
                  <i style={{ background: preset.colors.accent }} />
                </span>
                <span><strong>{preset.name}</strong><small>{preset.description}</small></span>
              </button>
            ))}
          </div>
          <label className="field font-size-field">
            <span>Font size: {appearance.fontSize}px</span>
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
          <div className="color-grid">
            {([
              ["accent", "Accent"],
              ["background", "Background"],
              ["panel", "Panels"],
              ["text", "Text"],
            ] as const).map(([key, label]) => (
              <label className="color-field" key={key}>
                <input type="color" value={appearance[key]} onChange={(e) => updateAppearance({ ...appearance, [key]: e.target.value })} />
                <span>{label}</span>
                <code>{appearance[key]}</code>
              </label>
            ))}
          </div>
          <button type="button" onClick={() => updateAppearance(DEFAULT_APPEARANCE)}>Reset appearance</button>
        </div>
      </section>

      <div className="settings-actions">
        <span className={message.startsWith("4") ? "danger-text" : "muted"}>{message}</span>
        <button className="primary" type="submit" disabled={busy}>{busy ? "Working…" : "Save settings"}</button>
      </div>
    </form>
  );
}
