"""把 pandoc 产出的 docx 排成中文学术论文格式。

约定（与 paper.pdf 一致）：
- 正文 宋体 / Times New Roman 10.5pt，行距 1.5，首行缩进 2 字符；
- 标题 黑体：一级 16pt、二级 14pt、三级 12pt，段前段后留白；
- 表格 Table Grid、9pt、表头加粗；图注 9pt 居中；
- 参考文献 9pt、悬挂缩进；页眉短标题，页脚居中页码。
"""
from __future__ import annotations

import copy
import sys

import docx
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

BODY_CN, BODY_EN = '宋体', 'Times New Roman'
HEAD_CN, HEAD_EN = '黑体', 'Arial'


def set_run_fonts(run, cn: str, en: str) -> None:
    run.font.name = en
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn('w:rFonts'))
    if rfonts is None:
        rfonts = OxmlElement('w:rFonts')
        rpr.append(rfonts)
    rfonts.set(qn('w:ascii'), en)
    rfonts.set(qn('w:hAnsi'), en)
    rfonts.set(qn('w:eastAsia'), cn)


def set_style_fonts(style, cn: str, en: str) -> None:
    style.font.name = en
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn('w:rFonts'))
    if rfonts is None:
        rfonts = OxmlElement('w:rFonts')
        rpr.append(rfonts)
    rfonts.set(qn('w:ascii'), en)
    rfonts.set(qn('w:hAnsi'), en)
    rfonts.set(qn('w:eastAsia'), cn)


def add_page_field(paragraph) -> None:
    run = paragraph.add_run()
    for kind, text in (('begin', None), ('instr', ' PAGE '), ('end', None)):
        if kind == 'instr':
            el = OxmlElement('w:instrText')
            el.set(qn('xml:space'), 'preserve')
            el.text = text
        else:
            el = OxmlElement('w:fldChar')
            el.set(qn('w:fldCharType'), kind)
        run._element.append(el)


def main(src: str, dst: str) -> int:
    d = docx.Document(src)

    # ---------- 页面 ----------
    for section in d.sections:
        section.page_width, section.page_height = Cm(21.0), Cm(29.7)
        section.left_margin = section.right_margin = Cm(2.5)
        section.top_margin, section.bottom_margin = Cm(2.6), Cm(2.4)
        section.header_distance, section.footer_distance = Cm(1.4), Cm(1.4)

    # ---------- 样式 ----------
    styles = d.styles
    normal = styles['Normal']
    set_style_fonts(normal, BODY_CN, BODY_EN)
    normal.font.size = Pt(10.5)
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.first_line_indent = Pt(21)

    heading_spec = {
        'Heading 1': (16, 12, 8),
        'Heading 2': (14, 10, 6),
        'Heading 3': (12, 8, 4),
        'Heading 4': (11, 6, 3),
    }
    for name, (size, before, after) in heading_spec.items():
        st = styles[name]
        set_style_fonts(st, HEAD_CN, HEAD_EN)
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = RGBColor(0, 0, 0)
        st.paragraph_format.space_before = Pt(before)
        st.paragraph_format.space_after = Pt(after)
        st.paragraph_format.first_line_indent = Pt(0)
        st.paragraph_format.keep_with_next = True
        st.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        st.paragraph_format.line_spacing = 1.3

    for name in ('Abstract', 'Body Text', 'First Paragraph', 'Bibliography'):
        if name in [s.name for s in styles]:
            set_style_fonts(styles[name], BODY_CN, BODY_EN)

    # ---------- 标题块（pandoc 丢了 \maketitle） ----------
    title = ('多主体协同带来判别增量吗？')
    subtitle = '面向跨境金融风险的可审计预警系统 CBR-MAW 的消融研究'
    first = d.paragraphs[0]
    title_paragraphs = []
    for text, size, bold, space_after in (
        (title, 18, True, 4),
        (subtitle, 13, True, 10),
        ('CBR-MAW 研究组', 10.5, False, 2),
        ('预印本 · 2026 年 11 月 28 日', 10.5, False, 14),
    ):
        p = first.insert_paragraph_before()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Pt(0)
        p.paragraph_format.space_after = Pt(space_after)
        run = p.add_run(text)
        set_run_fonts(run, HEAD_CN if bold else BODY_CN, HEAD_EN if bold else BODY_EN)
        run.font.size = Pt(size)
        run.bold = bold
        title_paragraphs.append(p._p)

    # ---------- 摘要标题 ----------
    for p in d.paragraphs[:8]:
        if p.style.name == 'Abstract Title' and p.text.strip() == 'Abstract':
            for r in list(p.runs):
                r._element.getparent().remove(r._element)
            run = p.add_run('摘要')
            set_run_fonts(run, HEAD_CN, HEAD_EN)
            run.font.size = Pt(14)
            run.bold = True
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.first_line_indent = Pt(0)

    # ---------- 英文摘要小标题 ----------
    for p in d.paragraphs:
        if p.text.strip().startswith('Cross-border financial risk early warning'):
            head = p.insert_paragraph_before()
            head.alignment = WD_ALIGN_PARAGRAPH.CENTER
            head.paragraph_format.first_line_indent = Pt(0)
            head.paragraph_format.space_before = Pt(0)
            head.paragraph_format.space_after = Pt(6)
            run = head.add_run('Abstract')
            set_run_fonts(run, HEAD_CN, HEAD_EN)
            run.font.size = Pt(14)
            run.bold = True
            break

    # ---------- 关键词标签加粗 ----------
    for p in d.paragraphs:
        text = p.text.strip()
        for label in ('关键词：', 'Keywords:'):
            if text.startswith(label) and p.runs:
                first_run = p.runs[0]
                if first_run.text.startswith(label):
                    continue  # 已是独立 run
                # 把标签从首个 run 里拆出来单独加粗
                rest = first_run.text[len(label):]
                first_run.text = label
                first_run.bold = True
                # 关键词行左对齐：两端对齐会把中文关键词拉出大空隙
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                tail = p.add_run(rest)
                tail.bold = False
                set_run_fonts(tail, BODY_CN, BODY_EN)
                tail.font.size = Pt(10.5)
                # 保持顺序：把新 run 移到首个 run 之后
                first_run._element.addnext(tail._element)
                break

    # ---------- 正文段落 ----------
    for p in d.paragraphs:
        # 必须持有元素引用再比较：lxml 代理对象在无引用时会被回收，id() 不可靠。
        if any(p._p is el for el in title_paragraphs):
            continue
        name = p.style.name
        if name.startswith('Heading') or name in ('Abstract Title', 'Title'):
            continue
        if name == 'Bibliography':
            # pandoc 用制表符对齐编号；在 Word 里会跳到默认制表位，出现大空隙。
            # 改为悬挂缩进 + 普通空格。
            for r in p.runs:
                if '\t' in r.text:
                    r.text = r.text.replace('\t', ' ')
            p.paragraph_format.left_indent = Cm(0.8)
            p.paragraph_format.first_line_indent = Cm(-0.8)
            p.paragraph_format.space_after = Pt(2)
            for r in p.runs:
                set_run_fonts(r, BODY_CN, BODY_EN)
                r.font.size = Pt(9)
            continue
        # 图题：以「图 N」开头
        text = p.text.strip()
        if text.startswith('图 ') and len(text) < 400 and text[2:3].isdigit():
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.first_line_indent = Pt(0)
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(10)
            for r in p.runs:
                set_run_fonts(r, BODY_CN, BODY_EN)
                r.font.size = Pt(9)
            continue
        # 含图片的段落居中
        if p._element.findall('.//' + qn('w:drawing')):
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.first_line_indent = Pt(0)
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(0)
            continue
        # 列表项不首行缩进
        if p._element.findall('.//' + qn('w:numPr')):
            p.paragraph_format.first_line_indent = Pt(0)
        for r in p.runs:
            set_run_fonts(r, BODY_CN, BODY_EN)
            r.font.size = Pt(10.5)

    # ---------- 表题（pandoc 用 Table Caption 样式，缺「表 N」前缀） ----------
    table_captions = [p for p in d.paragraphs if p.style.name == 'Table Caption']
    for idx, p in enumerate(table_captions, 1):
        text = p.text.strip()
        for r in list(p.runs):
            r._element.getparent().remove(r._element)
        label = p.add_run(f'表 {idx}　')
        label.bold = True
        set_run_fonts(label, BODY_CN, BODY_EN)
        label.font.size = Pt(9)
        body_run = p.add_run(text)
        set_run_fonts(body_run, BODY_CN, BODY_EN)
        body_run.font.size = Pt(9)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Pt(0)
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.keep_with_next = True

    # ---------- 表格 ----------
    # pandoc 产出的 docx 不含内建表格样式，直接写 tblBorders。
    def add_table_borders(table) -> None:
        tbl_pr = table._tbl.tblPr
        borders = OxmlElement('w:tblBorders')
        for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
            el = OxmlElement(f'w:{edge}')
            el.set(qn('w:val'), 'single')
            el.set(qn('w:sz'), '4')
            el.set(qn('w:space'), '0')
            el.set(qn('w:color'), '808080')
            borders.append(el)
        tbl_pr.append(borders)

    def tight_cells(table) -> None:
        tbl_pr = table._tbl.tblPr
        mar = OxmlElement('w:tblCellMar')
        for edge, w in (('top', 20), ('bottom', 20), ('left', 48), ('right', 48)):
            el = OxmlElement(f'w:{edge}')
            el.set(qn('w:w'), str(w))
            el.set(qn('w:type'), 'dxa')
            mar.append(el)
        tbl_pr.append(mar)

    for table in d.tables:
        add_table_borders(table)
        tight_cells(table)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = True
        for row_index, row in enumerate(table.rows):
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.first_line_indent = Pt(0)
                    p.paragraph_format.space_before = Pt(0)
                    p.paragraph_format.space_after = Pt(0)
                    p.paragraph_format.line_spacing = 1.0
                    for r in p.runs:
                        set_run_fonts(r, BODY_CN, BODY_EN)
                        r.font.size = Pt(8.5)
                        if row_index == 0:
                            r.bold = True
        # 表头重复
        tr = table.rows[0]._tr
        trPr = tr.get_or_add_trPr()
        tblHeader = OxmlElement('w:tblHeader')
        tblHeader.set(qn('w:val'), 'true')
        trPr.append(tblHeader)

    # ---------- 页眉 / 页脚 ----------
    section = d.sections[0]
    header = section.header
    header.is_linked_to_previous = False
    hp = header.paragraphs[0]
    hp.text = ''
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hr = hp.add_run('多主体协同带来判别增量吗？')
    set_run_fonts(hr, BODY_CN, BODY_EN)
    hr.font.size = Pt(9)
    hr.italic = True
    hr.font.color.rgb = RGBColor(0x59, 0x59, 0x59)
    # 页眉下横线
    pPr = hp._p.get_or_add_pPr()
    borders = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '4')
    bottom.set(qn('w:space'), '1')
    bottom.set(qn('w:color'), '999999')
    borders.append(bottom)
    pPr.append(borders)

    footer = section.footer
    footer.is_linked_to_previous = False
    fp = footer.paragraphs[0]
    fp.text = ''
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_page_field(fp)
    for r in fp.runs:
        set_run_fonts(r, BODY_CN, BODY_EN)
        r.font.size = Pt(9)

    # ---------- 文档属性 ----------
    cp = d.core_properties
    cp.title = '多主体协同带来判别增量吗？——面向跨境金融风险的可审计预警系统 CBR-MAW 的消融研究'
    cp.author = 'CBR-MAW 研究组'
    cp.subject = '跨境金融风险 · 多智能体系统 · 可审计 AI · 消融研究'
    cp.keywords = '跨境金融风险; 多智能体; 可审计人工智能; 时点一致性; 消融研究; 金融压力指数'
    cp.comments = '由 paper.tex 与 artifacts/bench 自动生成；数字不可手改。'

    d.save(dst)
    print(f'saved {dst}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
