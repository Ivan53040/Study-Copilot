// Small helpers shared by the notes workspace: vault paths, tree order, slugs.

import type React from "react";
import type { TreeNode } from "../../types";

/** Heading anchor id, matching the ids rendered in reading view. */
export const slug = (s: string) =>
  s
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .replace(/\s+/g, "-")
    .replace(/^-+|-+$/g, "");

export const stripExt = (name: string) => name.replace(/\.(md|markdown|txt)$/i, "");
export const basename = (p: string) => p.split("/").pop() ?? p;
export const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** Folder part of a vault path, with a trailing slash ("" at the root). */
export const folderOf = (path: string | null | undefined) =>
  path?.includes("/") ? path.slice(0, path.lastIndexOf("/") + 1) : "";

/** Empty "new tab" placeholders are ids like "new:3", not paths. */
export const isNewTab = (id: string | null) => !!id && id.startsWith("new:");

export const isTextNote = (path: string) => /\.(md|markdown|txt)$/i.test(path);

/** Plain text of rendered Markdown children (for heading ids). */
export function toText(children: React.ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(toText).join("");
  if (children && typeof children === "object" && "props" in (children as any))
    return toText((children as any).props.children);
  return "";
}

export function collectFolders(node: TreeNode, acc: string[] = []): string[] {
  node.children?.forEach((c) => {
    if (c.type === "folder") {
      acc.push(c.path);
      collectFolders(c, acc);
    }
  });
  return acc;
}

/** "A/B/c.md" -> ["A", "A/B"] */
export function ancestorsOf(path: string): string[] {
  const parts = path.split("/");
  const out: string[] = [];
  for (let i = 1; i < parts.length; i++) out.push(parts.slice(0, i).join("/"));
  return out;
}

/** Folders first, then files, each in natural (numeric-aware) name order. */
export function sortChildren(children: TreeNode[], dir: "asc" | "desc"): TreeNode[] {
  const folders = children.filter((c) => c.type === "folder");
  const files = children.filter((c) => c.type === "file");
  const collate = (a: string, b: string) =>
    a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
  const cmp = (a: TreeNode, b: TreeNode) =>
    dir === "asc" ? collate(a.name, b.name) : collate(b.name, a.name);
  folders.sort(cmp);
  files.sort(cmp);
  return [...folders, ...files];
}

/** Every note name in the tree (without extension), for [[ autocomplete. */
export function noteNames(tree: TreeNode | null | undefined): string[] {
  const names = new Set<string>();
  const walk = (node: TreeNode | null | undefined) => {
    if (!node) return;
    if (node.type === "file" && isTextNote(node.name)) names.add(stripExt(node.name));
    node.children?.forEach(walk);
  };
  walk(tree);
  return [...names].sort((a, b) => a.localeCompare(b));
}
