import re, pathlib

root = pathlib.Path(__file__).resolve().parents[1]
tex = (root / 'paper.tex').read_text(encoding='utf-8')

# ---- 1) 收集宏值（macros.tex + mem_ablation.tex）
macros = {}
for name in ('tables/macros.tex', 'tables/mem_ablation.tex'):
    f = root / name
    if not f.exists():
        continue
    for m in re.finditer(r'\\csname res@([^\\]+)\\endcsname\{([^}]*)\}', f.read_text(encoding='utf-8')):
        macros[m.group(1)] = m.group(2)
print('macros loaded:', len(macros))

# ---- 2) 正文
body = tex[tex.index(r'\begin{document}') + len(r'\begin{document}'):tex.index(r'\end{document}')]

# 去掉排版专用命令
for junk in (r'\sloppy', r'\emergencystretch=3em', r'\maketitle', r'\clearpage'):
    body = body.replace(junk, '')
body = re.sub(r'\\bibliographystyle\{[^}]*\}', '', body)
body = re.sub(r'\\bibliography\{[^}]*\}', '', body)

# ---- 3) 图：TikZ → PNG
figs = re.findall(r'\\begin\{figure\}.*?\\end\{figure\}', body, re.S)
for i, block in enumerate(figs, 1):
    cap = re.search(r'\\caption\{(.*?)\}\s*\\label', block, re.S)
    caption = cap.group(1).strip() if cap else ''
    body = body.replace(block, f"""

\\begin{{center}}
\\includegraphics[width=0.94\\textwidth]{{figs/fig{i}.png}}
\\end{{center}}

\\noindent\\textbf{{图 {i}}}\\!\\,{caption}

""")
print('figures replaced:', len(figs))

# ---- 4) 宏展开（\RESULT 与 \TOPFILL）
def expand(m):
    a, b = m.group(1), m.group(2).replace('\\_', '_')
    return macros.get(f'{a}@{b}', '--')
body = re.sub(r'\\RESULT\{([^{}]+)\}\{([^{}]+)\}', expand, body)

# ---- 5) 交叉引用 → 字面编号
body = re.sub(r'图~?\\ref\{fig:[^}]+\}', '图', body)
tabs = {'tab:processes': 1, 'tab:r0r5': 2, 'tab:arms': 3, 'tab:main': 4,
        'tab:mcnemar': 5, 'tab:coverage': 6, 'tab:masking': 7,
        'tab:placebo': 8, 'tab:circularity': 9}
body = re.sub(r'表~?\\ref\{([^}]+)\}', lambda m: f"表 {tabs.get(m.group(1), '?')}", body)
secs = {'sec:related': 2, 'sec:arch': 3, 'sec:protocol': 4, 'sec:results': 5,
        'sec:memory-ablation': '5.6', 'sec:discussion': 6, 'sec:threats': 7}
body = re.sub(r'第~?\\ref\{([^}]+)\}~?节', lambda m: f"第 {secs.get(m.group(1), '?')} 节", body)
body = re.sub(r'附录~?\\ref\{([^}]+)\}', '附录 A', body)

# ---- 6) 去掉残留 label / 环境噪声
body = re.sub(r'\\label\{[^}]*\}', '', body)
body = body.replace(r'\appendix', '')

# ---- 7) 中文断行不产生空格：LaTeX 源码的换行被 pandoc 变成空格，
# 中文句子里就会出现「协同 被广泛假设」这类空隙。只在**非空行**的换行处、
# 且两侧均为中文/中文标点时删除空白。
CJK = r'\u4e00-\u9fff'
before = body.count('\n')
# 行尾/行首若有空格，单靠 \n 的 lookbehind 会漏；这里显式吃掉两侧空白，
# 但仍要求**只有一行换行**（不跨段落）。
body = re.sub(rf'(?<=[{CJK}，。；：、）】”])[ \t]*\n[ \t]*(?=[{CJK}（【“])', '', body)
body = re.sub(rf'(?<=[{CJK}，。；：、）】”])[ \t]+(?=[{CJK}（【“])', '', body)
print('cjk joins applied; newlines', before, '->', body.count('\n'))

out = root / 'word' / 'paper_docx.tex'
out.write_text(body, encoding='utf-8')
print('written', out, len(body), 'chars')
