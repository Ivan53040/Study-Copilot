// Appearance preferences (per device): colour palette, light/dark mode, reading
// font, text size and the name used in the greeting. Colours themselves live in
// styles/base.css (Clay) and styles/palettes.css as token sets keyed off
// <html data-palette="…" data-theme="light|dark">.

export type ThemeMode = "light" | "dark" | "system";
export type ReadingFont = "serif" | "sans";

type Swatches = { bg: string; sidebar: string; panel: string; accent: string; "user-bubble": string };

/** Colour palettes (each has light + dark variants; tokens in styles/palettes.css). */
export const PALETTES: { id: string; label: string; note: string; light: Swatches; dark: Swatches }[] = [
  { id: "clay", label: "Clay", note: "Warm ivory, terracotta", light: {"bg": "#faf9f5", "sidebar": "#f5f4ed", "panel": "#ffffff", "accent": "#d97757", "user-bubble": "#efece3"}, dark: {"bg": "#262624", "sidebar": "#1f1e1d", "panel": "#30302e", "accent": "#d97757", "user-bubble": "#141413"} },
  { id: "ocean", label: "Ocean", note: "Cool slate, calm blue", light: {"bg": "#f5f7fa", "sidebar": "#eef2f6", "panel": "#ffffff", "accent": "#3a86c8", "user-bubble": "#e7edf5"}, dark: {"bg": "#1b2230", "sidebar": "#151b26", "panel": "#232c3b", "accent": "#5ea3e0", "user-bubble": "#10151e"} },
  { id: "forest", label: "Forest", note: "Sage paper, deep green", light: {"bg": "#f6f8f3", "sidebar": "#eef2ea", "panel": "#ffffff", "accent": "#4f8a5b", "user-bubble": "#e7ede1"}, dark: {"bg": "#1c231e", "sidebar": "#161c17", "panel": "#242d26", "accent": "#7dbb89", "user-bubble": "#111612"} },
  { id: "lavender", label: "Lavender", note: "Soft lilac, violet", light: {"bg": "#f8f7fb", "sidebar": "#f1eff8", "panel": "#ffffff", "accent": "#7c5cc4", "user-bubble": "#ebe7f5"}, dark: {"bg": "#1e1b27", "sidebar": "#18161f", "panel": "#27232f", "accent": "#a58be6", "user-bubble": "#131118"} },
  { id: "rose", label: "Rose", note: "Blush paper, raspberry", light: {"bg": "#fbf7f7", "sidebar": "#f6eff0", "panel": "#ffffff", "accent": "#c2577a", "user-bubble": "#f2e7e9"}, dark: {"bg": "#251d20", "sidebar": "#1d1719", "panel": "#2d2427", "accent": "#e58aa6", "user-bubble": "#161113"} },
  { id: "graphite", label: "Graphite", note: "Neutral grey, ink", light: {"bg": "#f7f7f7", "sidebar": "#f0f0f0", "panel": "#ffffff", "accent": "#525252", "user-bubble": "#ececec"}, dark: {"bg": "#1a1a1a", "sidebar": "#141414", "panel": "#242424", "accent": "#d4d4d4", "user-bubble": "#0f0f0f"} },
];

export type Palette = (typeof PALETTES)[number]["id"];

export type Appearance = {
  theme: ThemeMode;
  palette: Palette;
  readingFont: ReadingFont;
  fontSize: number;
  name: string;
};

const STORAGE_KEY = "study-copilot-appearance";

export const DEFAULT_APPEARANCE: Appearance = {
  theme: "system",
  palette: "clay",
  readingFont: "serif",
  fontSize: 14,
  name: "",
};

const darkQuery = () =>
  typeof window !== "undefined" && window.matchMedia
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;

export function resolveTheme(mode: ThemeMode): "light" | "dark" {
  if (mode === "system") return darkQuery()?.matches ? "dark" : "light";
  return mode;
}

export function loadAppearance(): Appearance {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as Record<
      string,
      unknown
    >;
    const theme: ThemeMode =
      stored.theme === "light" || stored.theme === "dark" || stored.theme === "system"
        ? stored.theme
        : DEFAULT_APPEARANCE.theme;
    const fontSize =
      typeof stored.fontSize === "number" && stored.fontSize >= 12 && stored.fontSize <= 20
        ? stored.fontSize
        : DEFAULT_APPEARANCE.fontSize;
    const palette = PALETTES.some((item) => item.id === stored.palette)
      ? (stored.palette as Palette)
      : DEFAULT_APPEARANCE.palette;
    return {
      theme,
      palette,
      readingFont: stored.readingFont === "sans" ? "sans" : "serif",
      fontSize,
      name: typeof stored.name === "string" ? stored.name : "",
    };
  } catch {
    return DEFAULT_APPEARANCE;
  }
}

export function saveAppearance(value: Appearance) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    /* storage unavailable: keep the in-memory value */
  }
}

let systemListener: ((event: MediaQueryListEvent) => void) | null = null;

export function applyAppearance(value: Appearance) {
  const root = document.documentElement;
  const apply = () => {
    const resolved = resolveTheme(value.theme);
    root.dataset.theme = resolved;
    root.style.colorScheme = resolved;
    window.dispatchEvent(new CustomEvent("study-copilot-theme", { detail: resolved }));
  };
  apply();
  root.dataset.palette = value.palette;
  root.dataset.readingFont = value.readingFont;
  root.style.setProperty("--base-font-size", `${value.fontSize}px`);

  const query = darkQuery();
  if (query && systemListener) query.removeEventListener("change", systemListener);
  systemListener = null;
  if (query && value.theme === "system") {
    systemListener = () => apply();
    query.addEventListener("change", systemListener);
  }
}

export function isDarkTheme() {
  return document.documentElement.dataset.theme === "dark";
}
