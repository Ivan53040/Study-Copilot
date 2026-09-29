// Math (KaTeX) and code highlighting for rendered markdown. Split into its own
// chunk: it is fetched shortly after start-up, or as soon as something needs
// it, instead of weighing down the first load.
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

export { rehypeHighlight, rehypeKatex };
