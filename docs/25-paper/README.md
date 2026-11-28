# 论文工程说明（docs/25-paper）

本目录是正式消融实验的论文与生成物。**任何结果数字都不手写**：正文通过宏引用
`tables/macros.tex`，表格由 `tools/bench/analysis/render_tables.py` 从
`artifacts/bench/` 的真实产物生成。

## 文件

| 文件 | 来源 | 说明 |
|---|---|---|
| `paper.tex` | 手写（方法/协议/讨论） | 中文正文 + 英文摘要；结果句一律 `\RESULT{臂}{指标}` |
| `refs.bib` | 手写（逐条核实） | 经 DOI / arXiv API 核对标题、作者、年份 |
| `tables/*.tex` | **脚本生成**，勿手改 | 主表、McNemar、覆盖率、安慰剂、循环性、宏 |
| `paper.pdf` | `tectonic` 编译 | 21 页；三张 TikZ 图（拓扑、记忆检索、评估窗口） |
| `tables/` | 脚本生成 | 6 张表 + 149 个宏，正文数字全部经 `\RESULT` 注入 |
| `results.scored.json` | `score_arms.py` 输出副本 | 聚合指标（precision/CI/recall/lift/McNemar），供审计；逐时点原始产物在 `artifacts/bench/`（gitignored） |

## Word 版

- `CBR-MAW-论文.docx`：与 PDF 同源（`paper.tex` + `artifacts/bench`），24 页。
  正文宋体/Times 10.5pt、行距 1.5、首行缩进 2 字符；标题黑体；表格 8.5pt 带边框且表题
  「表 N」加粗；图注「图 N」加粗居中；页眉短标题、页脚居中页码；参考文献 IEEE 数字制。
- 重新生成（跑批更新数字后）：

  ```bash
  bash docs/25-paper/word/build_word.sh
  ```

  流水线：TikZ 图 → 300dpi PNG → 展开 `\RESULT` 宏 → 中文断行去空格 → pandoc（IEEE CSL）
  → python-docx 套版式。中间产物 `paper_docx.tex` / `paper_raw.docx` 不入库。
- 为什么不能直接 `pandoc paper.tex`：TikZ 图、自定义宏与浮动体 pandoc 都不处理，
  直接转会丢图、丢数字。

## 复现

```bash
# 1) 跑批（压力/平静各 60 个配对时点，4 分片）
PAIRS=60 SHARDS=4 bash tools/bench/run_console_shards.sh

# 2) 合并 → 评分 → 重生成表与宏 → 重编译 PDF
bash tools/bench/finalize.sh
```

单步等价于：

```bash
~/.cache/cbr-venv/bin/python tools/bench/analysis/merge_shards.py artifacts/bench --out artifacts/bench/console.json
~/.cache/cbr-venv/bin/python tools/bench/analysis/score_arms.py artifacts/bench/console.json
~/.cache/cbr-venv/bin/python tools/bench/analysis/render_tables.py --bench artifacts/bench
HTTPS_PROXY=http://127.0.0.1:7897 /home/xrak/rt/bin/tectonic docs/25-paper/paper.tex
```

## 版式约定

- `ctexart` + `fontset=fandol`：中文字形为 SC（不依赖系统字体，任何人重编译结果一致）；
  曾试 Noto CJK，但 TTC 会解析到 JP 字面，标题字形不对。
- 页边距 2.5cm、行距 1.38、首行缩进 2 字符、段间距 0（学术惯例，不同时用缩进与段距）。
- 图表标题 `caption` 小一号、标签加粗；`\RESULT`/`\TOPFILL` 之外禁止出现裸数字。
- 编译产物要求：**0 overfull hbox、0 undefined reference**（当前满足）。

## 生成规则（保证不编造）

1. **缺值写 `--`**，不写 0，也不回落到上一批次的数字。
2. **样本不足写「无法判定」**：`concl@*` 宏在 `n<30` 或缺指标时输出
   「无法判定（样本不足或指标缺失）」，不允许挑一个好看的说法。
3. **口径校验**：分片的 `model` / `base_url` / `arms` / `seed` 不一致时拒绝合并；
   同一 `as_of` 重复直接报错。
4. **未运行的实验不写进结果**：记忆开/关、槽位路由、弱证据组、模态子集均在
   第 7 节显式列为「未运行」，不给出任何效应量。

## 当前数据的已知边界

1. **主表（120 配对时点）在 E8 修复前跑出**：当时四个分片共用一份记忆库。配对检验不受
   影响（污染在臂间共享，McNemar 按对抵消），但绝对 lift 应按上界解读。投稿前应以
   隔离版重跑主表（命令见上，`roles.json` 与记忆目录均已修正）。
2. **记忆消融 n=16 < 30**：只作描述性结论（两条件预测完全一致），脚本会自动标注
   「样本不足，不作显著性主张」。跑满 ≥30 后重新执行 `finalize.sh` 即改判。

## 常见问题

- **PDF 里出现 `--`**：说明该指标在当前产物里不存在（例如未跑该臂）。
- **PDF 里出现「无法判定」**：样本量不足 30 或该指标未定义，属预期行为。
- **`partial_rate=1.000`**：历史上因编排预算低于真实消耗导致，已修
  （`roles.json` 的 `max_tokens_per_agent` 4000→16000），见 `docs/26 §2 E1`。
