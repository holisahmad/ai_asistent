"use client";

import type { ReactNode } from "react";

type Props = {
  content: string;
  onCitation?: (idx: number) => void;
};

const INLINE_RE = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\n]+\*|\[\d+\])/g;

function inlineNodes(text: string, keyBase: string, onCitation?: (idx: number) => void): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  INLINE_RE.lastIndex = 0;
  while ((match = INLINE_RE.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    const token = match[0];
    const key = `${keyBase}-${match.index}`;
    if (token.startsWith("`")) {
      nodes.push(
        <code
          key={key}
          className="rounded bg-slate-950/70 px-1.5 py-0.5 font-mono text-[0.8em] text-sky-200"
        >
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("**")) {
      nodes.push(
        <strong key={key} className="font-semibold text-white">
          {token.slice(2, -2)}
        </strong>,
      );
    } else if (token.startsWith("*")) {
      nodes.push(
        <em key={key} className="italic">
          {token.slice(1, -1)}
        </em>,
      );
    } else {
      const idx = Number(token.slice(1, -1));
      nodes.push(
        <button
          key={key}
          type="button"
          onClick={() => onCitation?.(idx)}
          title={`Lihat sumber [${idx}]`}
          className="mx-0.5 align-super text-sky-300 underline decoration-dotted hover:text-sky-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          [{idx}]
        </button>,
      );
    }
    last = match.index + token.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

/** Renderer markdown minimal & aman (React nodes, tanpa HTML mentah). */
export default function Markdown({ content, onCitation }: Props) {
  const blocks: ReactNode[] = [];
  const lines = content.split("\n");
  let paragraph: string[] = [];
  let list: string[] = [];
  let ordered: string[] = [];
  let code: string[] | null = null;

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    const text = paragraph.join(" ");
    blocks.push(
      <p key={`p-${blocks.length}`} className="leading-relaxed">
        {inlineNodes(text, `p${blocks.length}`, onCitation)}
      </p>,
    );
    paragraph = [];
  };
  const flushList = () => {
    if (list.length > 0) {
      blocks.push(
        <ul key={`ul-${blocks.length}`} className="ml-4 list-disc space-y-1">
          {list.map((item, i) => (
            <li key={i}>{inlineNodes(item, `ul${blocks.length}-${i}`, onCitation)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
    if (ordered.length > 0) {
      blocks.push(
        <ol key={`ol-${blocks.length}`} className="ml-4 list-decimal space-y-1">
          {ordered.map((item, i) => (
            <li key={i}>{inlineNodes(item, `ol${blocks.length}-${i}`, onCitation)}</li>
          ))}
        </ol>,
      );
      ordered = [];
    }
  };

  for (const line of lines) {
    if (code !== null) {
      if (line.trim().startsWith("```")) {
        blocks.push(
          <pre
            key={`code-${blocks.length}`}
            className="overflow-x-auto rounded-lg bg-slate-950/80 p-3 font-mono text-xs text-slate-200"
          >
            <code>{code.join("\n")}</code>
          </pre>,
        );
        code = null;
      } else {
        code.push(line);
      }
      continue;
    }
    if (line.trim().startsWith("```")) {
      flushParagraph();
      flushList();
      code = [];
      continue;
    }
    if (/^\s*#{1,4}\s+/.test(line)) {
      flushParagraph();
      flushList();
      blocks.push(
        <p key={`h-${blocks.length}`} className="font-semibold text-white">
          {inlineNodes(line.replace(/^\s*#{1,4}\s+/, ""), `h${blocks.length}`, onCitation)}
        </p>,
      );
      continue;
    }
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    if (bullet) {
      flushParagraph();
      ordered = [];
      list.push(bullet[1]);
      continue;
    }
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (numbered) {
      flushParagraph();
      list = [];
      ordered.push(numbered[1]);
      continue;
    }
    if (line.trim() === "") {
      flushParagraph();
      flushList();
      continue;
    }
    paragraph.push(line.trim());
  }
  if (code !== null) code.forEach((l) => paragraph.push(l));
  flushParagraph();
  flushList();

  return <div className="space-y-2 text-sm">{blocks}</div>;
}
