import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * 极简、安全的 Markdown 子集渲染（不引入富文本依赖，不使用 dangerouslySetInnerHTML）。
 * 支持：段落 / 标题 / 无序与有序列表 / 粗体 / 行内代码 / 链接 / 裸 URL。
 * 仅用于 assistant 回复等模型文本，避免 HTML 注入。
 */

type BlockType = "p" | "h3" | "h4" | "ul" | "ol";

interface Block {
  type: BlockType;
  lines: string[];
}

function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let current: Block | null = null;

  for (const rawLine of text.replace(/\r\n?/g, "\n").split("\n")) {
    const line = rawLine.trim();
    if (!line) {
      current = null;
      continue;
    }

    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push({
        type: heading[1].length === 1 ? "h3" : "h4",
        lines: [heading[2]],
      });
      current = null;
      continue;
    }

    const bullet = /^[-*•·]\s+(.*)$/.exec(line);
    if (bullet) {
      if (current?.type === "ul") {
        current.lines.push(bullet[1]);
      } else {
        current = { type: "ul", lines: [bullet[1]] };
        blocks.push(current);
      }
      continue;
    }

    const ordered = /^\d+[.)]\s+(.*)$/.exec(line);
    if (ordered) {
      if (current?.type === "ol") {
        current.lines.push(ordered[1]);
      } else {
        current = { type: "ol", lines: [ordered[1]] };
        blocks.push(current);
      }
      continue;
    }

    if (current?.type === "p") {
      current.lines.push(line);
    } else {
      current = { type: "p", lines: [line] };
      blocks.push(current);
    }
  }

  return blocks;
}

const LINK_CLASS =
  "text-info-ink underline decoration-1 underline-offset-2 transition-colors duration-150 hover:text-foreground";

function isSafeHref(href: string): boolean {
  return /^https?:\/\//i.test(href);
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const pattern =
    /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|https?:\/\/[^\s<>）)]+)/g;
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null = pattern.exec(text);
  let index = 0;

  while (match) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const token = match[0];
    const key = `${keyPrefix}-${index}`;

    if (token.startsWith("**") && token.endsWith("**")) {
      nodes.push(
        <strong key={key} className="font-semibold text-foreground">
          {token.slice(2, -2)}
        </strong>,
      );
    } else if (token.startsWith("`") && token.endsWith("`")) {
      nodes.push(
        <code
          key={key}
          className="rounded-sm bg-surface-2 px-1 py-0.5 font-mono text-caption text-foreground"
        >
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("[")) {
      const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token);
      if (link && isSafeHref(link[2])) {
        nodes.push(
          <a
            key={key}
            href={link[2]}
            target="_blank"
            rel="noreferrer noopener"
            className={LINK_CLASS}
          >
            {link[1]}
          </a>,
        );
      } else {
        nodes.push(token);
      }
    } else if (isSafeHref(token)) {
      nodes.push(
        <a
          key={key}
          href={token}
          target="_blank"
          rel="noreferrer noopener"
          className={LINK_CLASS}
        >
          {token}
        </a>,
      );
    } else {
      nodes.push(token);
    }

    lastIndex = match.index + token.length;
    index += 1;
    match = pattern.exec(text);
  }

  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

export function RichText({ text, className }: { text: string; className?: string }) {
  const blocks = parseBlocks(text);
  return (
    <div className={cn("space-y-2 text-body leading-relaxed", className)}>
      {blocks.map((block, blockIndex) => {
        const key = `block-${blockIndex}`;
        if (block.type === "h3") {
          return (
            <h3 key={key} className="pt-1 text-panel font-semibold text-foreground">
              {renderInline(block.lines[0], key)}
            </h3>
          );
        }
        if (block.type === "h4") {
          return (
            <h4 key={key} className="pt-1 text-body font-semibold text-foreground">
              {renderInline(block.lines[0], key)}
            </h4>
          );
        }
        if (block.type === "ul") {
          return (
            <ul key={key} className="list-disc space-y-1 pl-4 marker:text-muted-foreground">
              {block.lines.map((line, lineIndex) => (
                <li key={`${key}-${lineIndex}`}>{renderInline(line, `${key}-${lineIndex}`)}</li>
              ))}
            </ul>
          );
        }
        if (block.type === "ol") {
          return (
            <ol key={key} className="list-decimal space-y-1 pl-4 marker:text-muted-foreground">
              {block.lines.map((line, lineIndex) => (
                <li key={`${key}-${lineIndex}`}>{renderInline(line, `${key}-${lineIndex}`)}</li>
              ))}
            </ol>
          );
        }
        return (
          <p key={key} className="whitespace-pre-line">
            {renderInline(block.lines.join("\n"), key)}
          </p>
        );
      })}
    </div>
  );
}
