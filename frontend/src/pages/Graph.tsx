import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape, { type Core, type NodeSingular } from "cytoscape";
import coseBilkent from "cytoscape-cose-bilkent";
import { api } from "../api";
import type { VaultGraph } from "../types";

cytoscape.use(coseBilkent);

function folderHue(folder: string): string {
  let hue = 262;
  for (const character of folder) hue = (hue * 31 + character.charCodeAt(0)) % 360;
  return `hsl(${hue}, 48%, 55%)`;
}

function graphFingerprint(graph: VaultGraph): string {
  const source = [
    ...graph.nodes.map((node) => node.id).sort(),
    ...graph.edges.map((edge) => `${edge.source}->${edge.target}`).sort(),
  ].join("|");
  let hash = 2166136261;
  for (let index = 0; index < source.length; index++) {
    hash ^= source.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

function positionKey(fingerprint: string) {
  return `study-copilot.graph.positions.${fingerprint}`;
}

export function GraphPage({ onOpen }: { onOpen: (path: string) => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [graph, setGraph] = useState<VaultGraph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedTitle, setSelectedTitle] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const fingerprint = useMemo(() => graph ? graphFingerprint(graph) : "", [graph]);

  const loadGraph = () => {
    setLoading(true);
    setError(null);
    api
      .vaultGraph()
      .then(setGraph)
      .catch((reason) => setError((reason as Error).message))
      .finally(() => setLoading(false));
  };

  useEffect(loadGraph, []);

  useEffect(() => {
    if (!graph || !containerRef.current) return;
    const rootStyle = getComputedStyle(document.documentElement);
    const accent = rootStyle.getPropertyValue("--accent").trim() || "#8b5cf6";
    const text = rootStyle.getPropertyValue("--text").trim() || "#e5e7eb";
    const muted = rootStyle.getPropertyValue("--muted").trim() || "#8b93a7";

    const cy = cytoscape({
      container: containerRef.current,
      elements: [
        ...graph.nodes.map((node) => ({
          data: {
            id: node.id,
            title: node.title,
            folder: node.folder,
            degree: node.degree,
            size: Math.min(28, 7 + Math.sqrt(node.degree + 1) * 3.2),
            color: folderHue(node.folder),
          },
          classes: node.degree >= 10 ? "hub" : "",
        })),
        ...graph.edges.map((edge, index) => ({
          data: {
            id: `edge-${index}-${edge.source}-${edge.target}`,
            source: edge.source,
            target: edge.target,
          },
        })),
      ],
      style: [
        {
          selector: "node",
          style: {
            width: "data(size)",
            height: "data(size)",
            "background-color": "data(color)",
            "border-width": 0,
            opacity: 0.72,
            label: "",
            "font-family": "Inter, system-ui, sans-serif",
            "font-size": 12,
            "text-wrap": "ellipsis",
            "text-max-width": 180,
            "text-valign": "bottom",
            "text-margin-y": 7,
            color: text,
            "overlay-opacity": 0,
          },
        },
        {
          selector: "edge",
          style: {
            width: 0.7,
            "line-color": muted,
            opacity: 0.16,
            "curve-style": "straight",
            "overlay-opacity": 0,
          },
        },
        {
          selector: "node.hovered",
          style: {
            opacity: 1,
            label: "data(title)",
            "z-index": 20,
          },
        },
        {
          selector: "node.selected-node",
          style: {
            width: 24,
            height: 24,
            opacity: 1,
            label: "data(title)",
            "background-color": accent,
            "border-width": 2,
            "border-color": text,
            "font-size": 15,
            "font-weight": 600,
            "z-index": 50,
          },
        },
        {
          selector: "node.neighbor-node",
          style: {
            opacity: 1,
            "background-color": "#c8c9ce",
            "z-index": 30,
          },
        },
        {
          selector: "edge.focused-edge",
          style: {
            width: 1.35,
            "line-color": accent,
            opacity: 0.95,
            "z-index": 25,
          },
        },
        {
          selector: ".dimmed",
          style: { opacity: 0.12 },
        },
      ] as any,
      minZoom: 0.08,
      maxZoom: 4,
      boxSelectionEnabled: false,
      autoungrabify: false,
    });
    cyRef.current = cy;

    const clearFocus = () => {
      cy.elements().removeClass("dimmed selected-node neighbor-node focused-edge");
      setSelectedTitle(null);
    };

    const focusNode = (node: NodeSingular) => {
      cy.elements().removeClass("selected-node neighbor-node focused-edge");
      cy.elements().addClass("dimmed");
      node.removeClass("dimmed").addClass("selected-node");
      node.connectedEdges().removeClass("dimmed").addClass("focused-edge");
      node.neighborhood("node").removeClass("dimmed").addClass("neighbor-node");
      setSelectedTitle(node.data("title"));
    };

    let lastTapId = "";
    let lastTapTime = 0;
    cy.on("tap", "node", (event) => {
      const node = event.target as NodeSingular;
      const now = Date.now();
      focusNode(node);
      if (lastTapId === node.id() && now - lastTapTime < 350) {
        onOpen(node.id());
        lastTapId = "";
        lastTapTime = 0;
      } else {
        lastTapId = node.id();
        lastTapTime = now;
      }
    });
    cy.on("mouseover", "node", (event) => event.target.addClass("hovered"));
    cy.on("mouseout", "node", (event) => event.target.removeClass("hovered"));
    cy.on("tap", (event) => {
      if (event.target === cy) clearFocus();
    });

    const cached = localStorage.getItem(positionKey(fingerprint));
    let restored = false;
    if (cached) {
      try {
        const positions = JSON.parse(cached) as Record<string, { x: number; y: number }>;
        restored = cy.nodes().toArray().every((node) => !!positions[node.id()]);
        if (restored) {
          cy.nodes().positions((node) => positions[node.id()]);
          cy.fit(undefined, 55);
        }
      } catch {
        restored = false;
      }
    }

    if (!restored) {
      const layout = cy.layout({
        name: "cose-bilkent",
        animate: false,
        randomize: true,
        quality: "draft",
        nodeRepulsion: 5200,
        idealEdgeLength: 75,
        edgeElasticity: 0.45,
        nestingFactor: 0.9,
        gravity: 0.18,
        numIter: 1400,
        tile: false,
      } as any);
      cy.one("layoutstop", () => {
        const positions: Record<string, { x: number; y: number }> = {};
        cy.nodes().forEach((node) => {
          positions[node.id()] = node.position();
        });
        localStorage.setItem(positionKey(fingerprint), JSON.stringify(positions));
        cy.fit(undefined, 55);
      });
      layout.run();
    }

    cy.on("dragfree", "node", () => {
      const positions: Record<string, { x: number; y: number }> = {};
      cy.nodes().forEach((node) => {
        positions[node.id()] = node.position();
      });
      localStorage.setItem(positionKey(fingerprint), JSON.stringify(positions));
    });

    const observer = new ResizeObserver(() => {
      cy.resize();
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      cy.destroy();
      cyRef.current = null;
    };
  }, [fingerprint, graph, onOpen]);

  const fitGraph = () => cyRef.current?.fit(undefined, 55);

  const relayout = () => {
    const cy = cyRef.current;
    if (!cy || !fingerprint) return;
    localStorage.removeItem(positionKey(fingerprint));
    cy.elements().removeClass("dimmed selected-node neighbor-node focused-edge");
    setSelectedTitle(null);
    const layout = cy.layout({
      name: "cose-bilkent",
      animate: "end",
      animationDuration: 450,
      randomize: true,
      quality: "draft",
      nodeRepulsion: 5200,
      idealEdgeLength: 75,
      gravity: 0.18,
      numIter: 1400,
      tile: false,
    } as any);
    cy.one("layoutstop", () => {
      const positions: Record<string, { x: number; y: number }> = {};
      cy.nodes().forEach((node) => {
        positions[node.id()] = node.position();
      });
      localStorage.setItem(positionKey(fingerprint), JSON.stringify(positions));
      cy.fit(undefined, 55);
    });
    layout.run();
  };

  return (
    <div className="graph-page">
      <div className="graph-header">
        <div>
          <h1 className="page-title">Graph</h1>
          <p className="page-sub">
            Click to focus a note and its links. Double-click to open it.
            {graph && <> · {graph.stats.notes} notes, {graph.stats.links} links</>}
          </p>
        </div>
        <div className="graph-controls">
          {selectedTitle && <span className="graph-selected">{selectedTitle}</span>}
          <button onClick={fitGraph}>Fit</button>
          <button onClick={relayout}>Relayout</button>
          <button onClick={loadGraph} disabled={loading}>Refresh</button>
        </div>
      </div>
      {error && <div className="warn-banner">{error}</div>}
      <div className="graph-canvas" ref={containerRef}>
        {loading && <div className="graph-loading">Loading graph…</div>}
      </div>
    </div>
  );
}
