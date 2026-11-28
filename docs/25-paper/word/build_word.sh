#!/usr/bin/env bash
# 从 paper.tex 生成 Word 论文（docs/25-paper/CBR-MAW-论文.docx）。
#
# 为什么不是直接 pandoc：LaTeX 里有 TikZ 图、自定义 \RESULT 宏与浮动体，
# pandoc 都处理不了。这里的流水线是：
#   1. 把 3 张 TikZ 图单独编译成 300dpi PNG；
#   2. 预处理 tex：展开 \RESULT 宏（数值来自 artifacts/bench）、TikZ→图片、
#      交叉引用→字面编号、中文断行不留空格；
#   3. pandoc（IEEE 数字引用 + refs.bib）→ docx；
#   4. python-docx 套中文学术版式（宋体/黑体、行距、表题图注、页眉页码）。
#
# 用法：bash docs/25-paper/word/build_word.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

PAPER=docs/25-paper
WORD=$PAPER/word
PY="${CBR_PYTHON:-$HOME/.cache/cbr-venv/bin/python}"
TECTONIC="${TECTONIC:-/home/xrak/rt/bin/tectonic}"

step() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }

step "1/4 渲染 TikZ 图为 PNG"
mkdir -p "$WORD/figs"
"$PY" - "$PAPER/paper.tex" <<'PY'
import re, sys, pathlib
tex = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
blocks = re.findall(r'\\begin\{figure\}.*?\\end\{figure\}', tex, re.S)
pre = r"""\documentclass[UTF8,border=6pt]{standalone}
\usepackage[UTF8,scheme=plain,fontset=fandol]{ctex}
\usepackage{amsmath,amssymb}
\usepackage{tikz}
\usetikzlibrary{arrows.meta,positioning,fit,backgrounds,calc,decorations.pathreplacing}
\begin{document}
"""
for i, b in enumerate(blocks, 1):
    body = re.sub(r'^.*?\\begin\{tikzpicture\}', r'\\begin{tikzpicture}', b, flags=re.S)
    body = re.sub(r'\\end\{tikzpicture\}.*$', r'\\end{tikzpicture}', body, flags=re.S)
    pathlib.Path(f'/tmp/word_fig{i}.tex').write_text(pre + body + "\n\\end{document}\n", encoding='utf-8')
print(f'  {len(blocks)} 张图')
PY
for i in 1 2 3; do
  HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7897}" "$TECTONIC" "/tmp/word_fig$i.tex" >/dev/null 2>&1
  pdftoppm -r 300 -png -singlefile "/tmp/word_fig$i.pdf" "$WORD/figs/fig$i"
done

step "2/4 预处理 LaTeX（宏展开 / 图替换 / 中文断行）"
"$PY" "$WORD/prepare_tex.py"

step "3/4 pandoc → docx"
if [ ! -f "$WORD/ieee.csl" ]; then
  echo "缺少 ieee.csl（数字引用样式）；请先下载：" >&2
  echo "  curl -sL -o $WORD/ieee.csl https://raw.githubusercontent.com/citation-style-language/styles/master/ieee.csl" >&2
  exit 2
fi
(cd "$WORD" && pandoc paper_docx.tex -f latex -t docx -o paper_raw.docx \
   --bibliography=../refs.bib --citeproc --csl=ieee.csl)

step "4/4 套中文学术版式"
"$PY" "$WORD/postprocess_docx.py" "$WORD/paper_raw.docx" "$WORD/CBR-MAW-论文.docx"
cp "$WORD/CBR-MAW-论文.docx" "$PAPER/CBR-MAW-论文.docx"

printf '\n\033[1;32m✔ 完成\033[0m → %s/CBR-MAW-论文.docx\n' "$PAPER"
