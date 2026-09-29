// Dragging in the notes workspace:
// - tree rows onto a folder (move) or onto the open note (insert a link);
// - files from the desktop onto the window (desktop app only): import them
//   into the folder under the pointer, or link them from the open note.

import { useEffect, useState } from "react";
import { api } from "../../api";

export type TreeDrag = {
  path: string;
  type: "file" | "folder";
  x: number;
  y: number;
  target: string | null;
  overNote: boolean;
};

/** Mouse-driven drag of tree rows onto a folder or the open note. */
export function useTreeDrag({
  onMoveToFolder,
  onLinkIntoNote,
}: {
  onMoveToFolder: (source: string, folder: string) => void;
  onLinkIntoNote: (source: string) => void;
}) {
  const [drag, setDrag] = useState<TreeDrag | null>(null);

  const start = (
    source: string,
    sourceType: "file" | "folder",
    startEvent: React.MouseEvent,
  ) => {
    if (startEvent.button !== 0) return;
    startEvent.preventDefault();
    const startX = startEvent.clientX;
    const startY = startEvent.clientY;
    let dragging = false;

    const inspectTarget = (x: number, y: number) => {
      const element = document.elementFromPoint(x, y) as HTMLElement | null;
      const folder = element?.closest("[data-folder-path]") as HTMLElement | null;
      return {
        target: folder?.dataset.folderPath ?? null,
        overNote: !!element?.closest("[data-note-drop-zone]"),
      };
    };

    const onMove = (event: MouseEvent) => {
      if (!dragging && Math.hypot(event.clientX - startX, event.clientY - startY) < 6) return;
      dragging = true;
      document.body.style.userSelect = "none";
      document.body.style.cursor = "grabbing";
      const target = inspectTarget(event.clientX, event.clientY);
      setDrag({
        path: source,
        type: sourceType,
        x: event.clientX,
        y: event.clientY,
        ...target,
      });
    };

    const onUp = (event: MouseEvent) => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
      if (!dragging) return;

      const target = inspectTarget(event.clientX, event.clientY);
      setDrag(null);
      const blockClick = (clickEvent: MouseEvent) => {
        clickEvent.preventDefault();
        clickEvent.stopPropagation();
      };
      document.addEventListener("click", blockClick, { capture: true, once: true });

      if (target.overNote && sourceType === "file") {
        onLinkIntoNote(source);
      } else if (target.target !== null) {
        onMoveToFolder(source, target.target);
      }
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  return { drag, start };
}

/**
 * Files dropped onto the desktop app's window. Returns whether a drag is over
 * the window (for the drop overlay).
 */
export function useDesktopFileDrop({
  currentFolder,
  onImported,
  onLinkIntoNote,
  flash,
}: {
  /** Folder of the open note: the default import target. */
  currentFolder: string;
  onImported: (folder: string) => Promise<void>;
  onLinkIntoNote: (paths: string[]) => Promise<void>;
  flash: (message: string) => void;
}) {
  const [dropActive, setDropActive] = useState(false);

  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    let unlisten: (() => void) | undefined;
    import("@tauri-apps/api/webview")
      .then(({ getCurrentWebview }) =>
        getCurrentWebview()
        .onDragDropEvent(async (event) => {
          if (event.payload.type === "enter" || event.payload.type === "over") {
            setDropActive(true);
            return;
          }
          if (event.payload.type === "leave") {
            setDropActive(false);
            return;
          }
          if (event.payload.type !== "drop") return;
          setDropActive(false);
          const ratio = window.devicePixelRatio || 1;
          const element = document.elementFromPoint(
            event.payload.position.x / ratio,
            event.payload.position.y / ratio,
          ) as HTMLElement | null;
          const folderElement = element?.closest("[data-folder-path]") as HTMLElement | null;
          const overContent = !!element?.closest("[data-note-drop-zone]");
          const targetFolder = folderElement?.dataset.folderPath ?? currentFolder;
          try {
            const result = await api.vaultImport(event.payload.paths, targetFolder);
            await onImported(targetFolder);
            if (overContent) {
              await onLinkIntoNote(
                result.imported
                  .filter((item) => item.type === "file")
                  .map((item) => item.path),
              );
            } else {
              flash(`Imported ${result.count} item${result.count === 1 ? "" : "s"}`);
            }
          } catch (error) {
            flash((error as Error).message);
          }
        })
        .then((cleanup) => {
          unlisten = cleanup;
        }),
      )
      .catch((error) => flash(`File drop unavailable: ${(error as Error).message}`));
    return () => unlisten?.();
    // Re-subscribes when the drop targets change; the other callbacks only
    // refresh the tree or show a message, so a stale copy behaves the same.
  }, [onLinkIntoNote, currentFolder]);

  return dropActive;
}
