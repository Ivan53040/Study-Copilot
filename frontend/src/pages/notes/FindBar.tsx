// Find / replace in the current note, with undo and redo for replacements.

import { useState } from "react";
import { api } from "../../api";
import type { VaultNote } from "../../types";

type ReplaceStep = { path: string; before: string; after: string };

export function useFindReplace({
  note,
  active,
  source,
  setDraft,
  flash,
  reload,
}: {
  note: VaultNote | null;
  active: string | null;
  /** The text replacements apply to: the draft while editing, else the note. */
  source: () => string;
  setDraft: (content: string) => void;
  flash: (message: string) => void;
  reload: (path: string) => Promise<void>;
}) {
  const [mode, setMode] = useState<"find" | "replace" | null>(null);
  const [findText, setFindText] = useState("");
  const [replaceText, setReplaceText] = useState("");
  const [undoStack, setUndoStack] = useState<ReplaceStep[]>([]);
  const [redoStack, setRedoStack] = useState<ReplaceStep[]>([]);

  const find = () => {
    if (!findText) return;
    const browserFind = (window as typeof window & {
      find?: (
        text: string,
        caseSensitive?: boolean,
        backwards?: boolean,
        wrapAround?: boolean,
        wholeWord?: boolean,
        searchInFrames?: boolean,
        showDialog?: boolean,
      ) => boolean;
    }).find;
    if (browserFind) browserFind(findText, false, false, true, false, true, false);
  };

  const replace = async (replaceAll: boolean) => {
    if (!note || !findText) return;
    const before = source();
    const updated = replaceAll
      ? before.split(findText).join(replaceText)
      : before.replace(findText, replaceText);
    if (updated === before) {
      flash("No match found");
      return;
    }
    setUndoStack((history) => [...history, { path: note.path, before, after: updated }]);
    setRedoStack([]);
    setDraft(updated);
    await api.vaultSaveNote(note.path, updated);
    await reload(note.path);
    flash(replaceAll ? "Replaced all matches" : "Replaced next match");
  };

  const step = async (direction: "undo" | "redo") => {
    const stack = direction === "undo" ? undoStack : redoStack;
    const item = stack[stack.length - 1];
    if (!item) return;
    const content = direction === "undo" ? item.before : item.after;
    await api.vaultSaveNote(item.path, content);
    if (active === item.path) await reload(item.path);
    if (direction === "undo") {
      setUndoStack((history) => history.slice(0, -1));
      setRedoStack((history) => [...history, item]);
      flash("Replace undone");
    } else {
      setRedoStack((history) => history.slice(0, -1));
      setUndoStack((history) => [...history, item]);
      flash("Replace redone");
    }
  };

  return {
    mode,
    setMode,
    findText,
    setFindText,
    replaceText,
    setReplaceText,
    canUndo: undoStack.length > 0,
    canRedo: redoStack.length > 0,
    find,
    replace,
    step,
  };
}

export function FindBar({ findReplace }: { findReplace: ReturnType<typeof useFindReplace> }) {
  const {
    mode, setMode, findText, setFindText, replaceText, setReplaceText,
    canUndo, canRedo, find, replace, step,
  } = findReplace;
  if (!mode) return null;
  return (
    <div className="find-bar">
      <input
        autoFocus
        value={findText}
        onChange={(event) => setFindText(event.target.value)}
        onKeyDown={(event) => event.key === "Enter" && find()}
        placeholder="Find in note"
      />
      {mode === "replace" && (
        <input
          value={replaceText}
          onChange={(event) => setReplaceText(event.target.value)}
          placeholder="Replace with"
        />
      )}
      <button onClick={find}>Next</button>
      {mode === "replace" && (
        <>
          <button onClick={() => replace(false)}>Replace</button>
          <button onClick={() => replace(true)}>Replace all</button>
          <button disabled={!canUndo} onClick={() => step("undo")}>Undo</button>
          <button disabled={!canRedo} onClick={() => step("redo")}>Redo</button>
        </>
      )}
      <button className="icon-btn" onClick={() => setMode(null)}>×</button>
    </div>
  );
}
