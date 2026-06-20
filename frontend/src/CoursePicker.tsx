import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { VaultScope } from "./types";

function compact(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function distance(a: string, b: string) {
  const left = compact(a);
  const right = compact(b);
  const row = Array.from({ length: right.length + 1 }, (_, index) => index);
  for (let i = 1; i <= left.length; i++) {
    let diagonal = row[0];
    row[0] = i;
    for (let j = 1; j <= right.length; j++) {
      const above = row[j];
      row[j] = Math.min(
        row[j] + 1,
        row[j - 1] + 1,
        diagonal + (left[i - 1] === right[j - 1] ? 0 : 1),
      );
      diagonal = above;
    }
  }
  return row[right.length];
}

function score(scope: VaultScope, query: string) {
  const q = compact(query);
  const name = compact(scope.name);
  if (!q) return 0;
  if (name === q) return -100;
  if (name.startsWith(q)) return -80 + name.length - q.length;
  if (name.includes(q)) return -60 + name.indexOf(q);
  return distance(q, name);
}

function scopeDepth(scope: VaultScope) {
  const relative = scope.id.startsWith("folder:")
    ? scope.id.slice("folder:".length)
    : scope.id;
  return relative.split("/").filter(Boolean).length;
}

export function CoursePicker({
  value,
  onChange,
  courseOnly = false,
  maxDepth = 2,
}: {
  value: VaultScope | null;
  onChange: (scope: VaultScope) => void;
  courseOnly?: boolean;
  maxDepth?: number;
}) {
  const [scopes, setScopes] = useState<VaultScope[]>([]);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api
      .scopes()
      .then((result) =>
        setScopes(
          result.scopes.filter(
            (scope) =>
              scopeDepth(scope) <= maxDepth &&
              (!courseOnly || scope.kind === "course"),
          ),
        ),
      )
      .catch(() => {});
  }, [courseOnly, maxDepth]);

  const ranked = useMemo(
    () =>
      [...scopes]
        .sort((a, b) => score(a, query) - score(b, query) || a.name.localeCompare(b.name)),
    [scopes, query],
  );

  return (
    <div className="course-picker">
      <input
        value={open ? query : value?.name ?? ""}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => {
          setQuery("");
          setOpen(true);
        }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder={courseOnly ? "Search course…" : "Search course or folder…"}
      />
      {open && (
        <div className="course-menu">
          {ranked.map((scope) => (
            <button
              type="button"
              className={`course-option ${scope.id === value?.id ? "selected" : ""}`}
              key={scope.id}
              onMouseDown={() => {
                onChange(scope);
                setQuery("");
                setOpen(false);
              }}
            >
              <span>
                <strong>{scope.name}</strong>
                <small>{scope.kind === "course" ? "Course" : "Vault folder"}</small>
              </span>
              <small>{scope.documents} docs</small>
            </button>
          ))}
          {!ranked.length && <div className="course-empty">No matching scope found</div>}
        </div>
      )}
    </div>
  );
}
