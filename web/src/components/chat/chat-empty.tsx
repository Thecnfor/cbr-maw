import { ArrowUpRight, MessageSquare, Sparkles } from "lucide-react";

import { Card } from "@/components/ui/card";

const EXAMPLES = [
  "2024-08-05 前后跨境资金流出压力如何？主要驱动因子是什么？",
  "监管、投资、融资三类主体对当前风险的判断有哪些分歧？如何协调？",
  "如果人民币短期贬值 3%，对本组合与融资成本的影响如何？",
];

export function ChatEmpty({ onPick }: { onPick: (question: string) => void }) {
  return (
    <Card className="p-5 sm:p-6">
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg border border-border bg-surface-2 text-foreground">
          <MessageSquare className="size-4" aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h2 className="text-panel font-semibold tracking-tight text-foreground">
            从一个具体问题开始
          </h2>
          <p className="mt-1 text-caption leading-relaxed text-muted-foreground">
            问题会进入同一套协同编排：共享信号 → 工具与知识库 → 监管 / 投资 / 融资推理 →
            证据核验。回复附带引用来源，必要时生成关联决策卡。
          </p>
        </div>
      </div>

      <div className="mt-4">
        <div className="flex items-center gap-1.5 text-caption font-medium text-muted-foreground">
          <Sparkles className="size-3.5" aria-hidden="true" />
          试试这些问题
        </div>
        <ul className="mt-1.5 space-y-1.5">
          {EXAMPLES.map((question) => (
            <li key={question}>
              <button
                type="button"
                onClick={() => onPick(question)}
                className="group flex w-full items-start gap-2 rounded-lg border border-border bg-surface-1 px-3 py-2.5 text-left text-body text-foreground transition-colors duration-150 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="min-w-0 flex-1">{question}</span>
                <ArrowUpRight
                  className="mt-0.5 size-3.5 shrink-0 text-muted-foreground transition-colors duration-150 group-hover:text-foreground"
                  aria-hidden="true"
                />
              </button>
            </li>
          ))}
        </ul>
      </div>

      <p className="mt-3 border-t border-border pt-2 text-caption leading-relaxed text-muted-foreground">
        示例问题用于演示；若后端返回 503，说明核心模块尚未就绪，可在侧栏查看待就绪模块。
      </p>
    </Card>
  );
}
