"use client";

import type { ReactNode } from "react";

type Props = {
  content: string;
  onCitation?: (idx: number) => void;
};

const INLINE_RE = /(`[^`]+`|\*\*\*[^*]+\*\*\*|\*\*[^*]+\*\*|\*[^*\n]+\*|~~[^~]+~~|\[\d+\])/g;

function inlineNodes(
  text: string,
  keyBase: string,
  onCitation?: (idx: number) => void,
): ReactNode[] {
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
          className="rounded bg-slate-950/70 px-1.5 py-0.5 font-mono text-[0.82em] text-sky-200"
        >
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("***")) {
      nodes.push(
        <strong key={key} className="font-semibold italic text-white">
          {token.slice(3, -3)}
        </strong>,
      );
    } else if (token.startsWith("**")) {
      nodes.push(
        <strong key={key} className="font-semibold text-white">
          {token.slice(2, -2)}
        </strong>,
      );
    } else if (token.startsWith("~~")) {
      nodes.push(
        <s key={key} className="text-slate-500">
          {token.slice(2, -2)}
        </s>,
      );
    } else if (token.startsWith("*")) {
      nodes.push(
        <em key={key} className="italic text-slate-200">
          {token.slice(1, -1)}
        </em>,
      );
    } else {
      // sitasi [n]
      const idx = Number(token.slice(1, -1));
      nodes.push(
        <button
          key={key}
          type="button"
          onClick={() => onCitation?.(idx)}
          title={`Lihat sumber [${idx}]`}
          className="mx-0.5 inline-flex h-4 w-4 items-center justify-center rounded-full bg-sky-500/20 align-super text-[0.65em] font-medium text-sky-300 hover:bg-sky-500/40 hover:text-sky-100 focus:outline-none focus-visible:ring-1 focus-visible:ring-sky-400"
        >
          {idx}
        </button>,
      );
    }
    last = match.index + token.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

/** Markdown renderer lengkap: heading, list, tabel, blockquote, code block, HR. */
export default function Markdown({ content, onCitation }: Props) {
  const blocks: ReactNode[] = [];
  const lines = content.split("\n");
  let paragraph: string[] = [];
  let list: string[] = [];
  let ordered: string[] = [];
  let code: string[] | null = null;
  let codeLang = "";
  let tableRows: string[][] = [];
  let tableHeader: string[] = [];
  let inTable = false;
  let blockquote: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    const text = paragraph.join(" ");
    blocks.push(
      <p key={`p-${blocks.length}`} className="leading-relaxed text-slate-200">
        {inlineNodes(text, `p${blocks.length}`, onCitation)}
      </p>,
    );
    paragraph = [];
  };

  const flushList = () => {
    if (list.length > 0) {
      blocks.push(
        <ul key={`ul-${blocks.length}`} className="ml-5 list-disc space-y-1 text-slate-200">
          {list.map((item, i) => (
            <li key={i} className="leading-relaxed pl-1">
              {inlineNodes(item, `ul${blocks.length}-${i}`, onCitation)}
            </li>
          ))}
        </ul>,
      );
      list = [];
    }
    if (ordered.length > 0) {
      blocks.push(
        <ol key={`ol-${blocks.length}`} className="ml-5 list-decimal space-y-1 text-slate-200">
          {ordered.map((item, i) => (
            <li key={i} className="leading-relaxed pl-1">
              {inlineNodes(item, `ol${blocks.length}-${i}`, onCitation)}
            </li>
          ))}
        </ol>,
      );
      ordered = [];
    }
  };

  const flushTable = () => {
    if (tableHeader.length === 0 && tableRows.length === 0) return;
    blocks.push(
      <div key={`tbl-${blocks.length}`} className="overflow-x-auto rounded-lg border border-slate-700">
        <table className="w-full text-sm">
          {tableHeader.length > 0 && (
            <thead className="bg-slate-800/70">
              <tr>
                {tableHeader.map((h, i) => (
                  <th
                    key={i}
                    className="border-b border-slate-700 px-3 py-2 text-left font-semibold text-slate-100"
                  >
                    {inlineNodes(h.trim(), `th-${blocks.length}-${i}`, onCitation)}
                  </th>
                ))}
              </tr>
            </thead>
          )}
          <tbody>
            {tableRows.map((row, ri) => (
              <tr
                key={ri}
                className={ri % 2 === 0 ? "bg-slate-900/40" : "bg-slate-800/30"}
              >
                {row.map((cell, ci) => (
                  <td key={ci} className="border-b border-slate-800 px-3 py-2 text-slate-300">
                    {inlineNodes(cell.trim(), `td-${blocks.length}-${ri}-${ci}`, onCitation)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>,
    );
    tableHeader = [];
    tableRows = [];
    inTable = false;
  };

  const flushBlockquote = () => {
    if (blockquote.length === 0) return;
    blocks.push(
      <blockquote
        key={`bq-${blocks.length}`}
        className="border-l-2 border-sky-500/50 pl-4 italic text-slate-400"
      >
        {blockquote.map((line, i) => (
          <p key={i} className="leading-relaxed">
            {inlineNodes(line, `bq${blocks.length}-${i}`, onCitation)}
          </p>
        ))}
      </blockquote>,
    );
    blockquote = [];
  };

  for (const line of lines) {
    // ── code block ──────────────────────────────────────────────────────────
    if (code !== null) {
      if (line.trimStart().startsWith("```")) {
        blocks.push(
          <pre
            key={`code-${blocks.length}`}
            className="overflow-x-auto rounded-lg bg-slate-950/80 p-4 font-mono text-xs leading-relaxed text-slate-200"
          >
            {codeLang && (
              <div className="mb-2 text-slate-500 select-none">{codeLang}</div>
            )}
            <code>{code.join("\n")}</code>
          </pre>,
        );
        code = null;
        codeLang = "";
      } else {
        code.push(line);
      }
      continue;
    }

    if (line.trimStart().startsWith("```")) {
      flushParagraph();
      flushList();
      flushTable();
      flushBlockquote();
      codeLang = line.replace(/```/, "").trim();
      code = [];
      continue;
    }

    // ── blockquote ───────────────────────────────────────────────────────────
    const bqMatch = /^\s*>\s?(.*)/.exec(line);
    if (bqMatch) {
      flushParagraph();
      flushList();
      flushTable();
      blockquote.push(bqMatch[1]);
      continue;
    } else if (blockquote.length > 0) {
      flushBlockquote();
    }

    // ── horizontal rule ──────────────────────────────────────────────────────
    if (/^[-*_]{3,}\s*$/.test(line.trim())) {
      flushParagraph();
      flushList();
      flushTable();
      blocks.push(<hr key={`hr-${blocks.length}`} className="border-slate-700" />);
      continue;
    }

    // ── headings ─────────────────────────────────────────────────────────────
    const h1 = /^\s*#\s+(.+)$/.exec(line);
    const h2 = /^\s*##\s+(.+)$/.exec(line);
    const h3 = /^\s*###\s+(.+)$/.exec(line);
    const h4 = /^\s*#{4,}\s+(.+)$/.exec(line);

    if (h1 && !h2) {
      flushParagraph();
      flushList();
      flushTable();
      blocks.push(
        <h2 key={`h1-${blocks.length}`} className="mt-4 text-lg font-bold text-white first:mt-0">
          {inlineNodes(h1[1], `h1${blocks.length}`, onCitation)}
        </h2>,
      );
      continue;
    }
    if (h2 && !h3) {
      flushParagraph();
      flushList();
      flushTable();
      blocks.push(
        <h3 key={`h2-${blocks.length}`} className="mt-3 font-semibold text-slate-100 first:mt-0">
          {inlineNodes(h2[1], `h2${blocks.length}`, onCitation)}
        </h3>,
      );
      continue;
    }
    if (h3 && !h4) {
      flushParagraph();
      flushList();
      flushTable();
      blocks.push(
        <h4 key={`h3-${blocks.length}`} className="mt-2 font-medium text-slate-200 first:mt-0">
          {inlineNodes(h3[1], `h3${blocks.length}`, onCitation)}
        </h4>,
      );
      continue;
    }
    if (h4) {
      flushParagraph();
      flushList();
      flushTable();
      blocks.push(
        <p key={`h4-${blocks.length}`} className="mt-1 font-medium text-slate-300 first:mt-0">
          {inlineNodes(h4[1], `h4${blocks.length}`, onCitation)}
        </p>,
      );
      continue;
    }

    // ── tabel (GFM) ──────────────────────────────────────────────────────────
    if (line.trim().startsWith("|") && line.trim().endsWith("|")) {
      flushParagraph();
      flushList();
      const cells = line
        .trim()
        .slice(1, -1)
        .split("|")
        .map((c) => c.trim());

      // baris separator |---|---|
      if (cells.every((c) => /^:?-+:?$/.test(c))) {
        inTable = true;
        continue;
      }

      if (!inTable && tableHeader.length === 0) {
        tableHeader = cells;
      } else {
        tableRows.push(cells);
      }
      continue;
    } else if (inTable || tableHeader.length > 0) {
      flushTable();
    }

    // ── list ─────────────────────────────────────────────────────────────────
    const bullet = /^\s*[-*+]\s+(.+)$/.exec(line);
    if (bullet) {
      flushParagraph();
      if (ordered.length > 0) flushList();
      list.push(bullet[1]);
      continue;
    }

    const numbered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
    if (numbered) {
      flushParagraph();
      if (list.length > 0) flushList();
      ordered.push(numbered[1]);
      continue;
    }

    // ── empty line ───────────────────────────────────────────────────────────
    if (line.trim() === "") {
      flushParagraph();
      flushList();
      flushTable();
      continue;
    }

    // ── normal paragraph ─────────────────────────────────────────────────────
    // Bila sebelumnya list, flush dulu (list item baru baris baru)
    if (list.length > 0 || ordered.length > 0) flushList();
    paragraph.push(line.trim());
  }

  // flush sisa
  if (code !== null) code.forEach((l) => paragraph.push(l));
  flushParagraph();
  flushList();
  flushTable();
  flushBlockquote();

  return <div className="space-y-2.5 text-sm">{blocks}</div>;
}
