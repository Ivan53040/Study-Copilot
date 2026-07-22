// Obsidian-style local graph: the current note and its 1-2 hop wikilink
// neighborhood, as a small overlay over the Notes page.
import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape, { type NodeSingular } from "cytoscape";
import { api } from "./api";
import type { VaultGraph } from "./types";

interface LocalGraphProps {
  path: string;
  title: string;
  onOpen: (path: string) => void;
  onClose: () => void;
}

export function LocalGraph({ path, title, onOpen, onClose }: LocalGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [graph, setGraph] = useState<VaultGraph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hops, setHops] = useState<1 | 2>(1);

  useEffect(() => {
    api
      .vaultGraph()
      .then(setGraph)
      .catch((reason) => setError((reason as Error).message));
  }, []);

  const local = useMemo(() => {
    if (!graph) return null;
    const neighbors = new Map<string, Set<string>>();
    const link = (a: string, b: string) => {
      if (!neighbors.has(a)) neighbors.set(a, new Set());
      neighbors.get(a)!.add(b);
    };
    for (const edge of graph.edges) {
      link(edge.source, edge.target);
      link(edge.target, edge.source);
    }
    const keep = new Set<string>([path]);
    let frontier = [path];
    for (let hop = 0; hop < hops; hop++) {
      const next: string[] = [];
      for (const id of frontier) {
        for (const neighbor of neighbors.get(id) ?? []) {
          if (!keep.has(neighbor)) {
            keep.add(neighbor);
            next.push(neighbor);
          }
        }
      }
      frontier = next;
    }
    return {
      nodes: graph.nodes.filter((node) => keep.has(node.id)),
      edges: graph.edges.filter(
        (edge) => keep.has(edge.source) && keep.has(edge.target),
      ),
    };
  }, [graph, path, hops]);

  useEffect(() => {
    if (!local || !containerRef.current || local.nodes.length <= 1) return;
    const rootStyle = getComputedStyle(document.documentElement);
    const accent = rootStyle.getPropertyValue("--accent").trim() || "#8b5cf6";
    const text = rootStyle.getPropertyValue("--text").trim() || "#e5e7eb";
    const muted = rootStyle.getPropertyValue("--muted").trim() || "#8b93a7";

    const cy = cytoscape({
      container: containerRef.current,
      elements: [
        ...local.nodes.map((node) => ({
          data: { id: node.id, title: node.title, center: node.id === path },
        })),
        ...local.edges.map((edge, index) => ({
          data: { id: `e${index}`, source: edge.source, target: edge.target },
        })),
      ],
      style: [
        {
          selector: "node",
          style: {
            width: 14,
            height: 14,
            "background-color": muted,
            label: "data(title)",
            "font-family": "Inter, system-ui, sans-serif",
            "font-size": 11,
            "text-wrap": "ellipsis",
            "text-max-width": 140,
            "text-valign": "bottom",
            "text-margin-y": 6,
            color: text,
            "overlay-opacity": 0,
          },
        },
        {
          selector: "node[?center]",
          style: {
            width: 22,
            height: 22,
            "background-color": accent,
            "font-weight": 600,
            "font-size": 13,
          },
        },
        {
          selector: "edge",
          style: {
            width: 1,
            "line-color": muted,
            opacity: 0.35,
            "curve-style": "straight",
            "overlay-opacity": 0,
          },
        },
      ] as any,
      minZoom: 0.2,
      maxZoom: 4,
      boxSelectionEnabled: false,
    });

    cy.layout({ name: "cose", animate: false, padding: 40 } as any).run();
    cy.fit(undefined, 45);
    cy.on("tap", "node", (event) => {
      onOpen((event.target as NodeSingular).id());
    });

    const observer = new ResizeObserver(() => cy.resize());
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      cy.destroy();
    };
  }, [local, path, onOpen]);

  return (
    <>
      <div
        className="editor-menu-backdrop"
        style={{ zIndex: 179 }}
        onMouseDown={onClose}
      />
      <div className="local-graph-panel">
        <div className="local-graph-header">
          <span className="local-graph-title">Local graph — {title}</span>
          <div className="grow" />
          <button
            className={hops === 1 ? "active" : ""}
            onClick={() => setHops(1)}
          >
            1 hop
          </button>
          <button
            className={hops === 2 ? "active" : ""}
            onClick={() => setHops(2)}
          >
            2 hops
          </button>
          <button title="Close" onClick={onClose}>
            ✕
          </button>
        </div>
        {error && <div className="warn-banner">{error}</div>}
        {local && local.nodes.length <= 1 ? (
          <div className="small muted" style={{ padding: 14 }}>
            No linked notes yet — add some [[wikilinks]] first.
          </div>
        ) : (
          <div className="local-graph-canvas" ref={containerRef} />
        )}
      </div>
    </>
  );
}
