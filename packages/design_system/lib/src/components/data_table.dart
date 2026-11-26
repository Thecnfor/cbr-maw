import 'package:material_ui/material_ui.dart';

import '../layout/breakpoints.dart';
import '../tokens/colors.dart';
import '../tokens/tokens.dart';
import 'pressable.dart';

/// 表格列定义：`priority` 决定窄屏裁剪顺序（docs/07 §1.3、§3.1）。
@immutable
class CbrTableColumn<T> {
  const CbrTableColumn({
    required this.key,
    required this.title,
    required this.cell,
    this.priority = 1,
    this.align = Alignment.centerLeft,
    this.width,
  });

  final String key;
  final String title;
  final Widget Function(BuildContext context, T row) cell;

  /// 1 = 必显，2 = `<1100` 隐藏，3 = `<840` 隐藏（docs/07 §1.3）。
  final int priority;
  final Alignment align;
  final double? width;
}

/// 响应式表格（docs/06 §6.2 `DataTableVirtual`、docs/07 §3.1）。
///
/// - `< 600`：转卡片，排序字段置顶（首列）。
/// - `600–839`：按优先级裁剪 + 横向滚动。
/// - `≥ 840`：冻结首列 + 横向滚动。
///
/// 只做展示；排序状态由调用方持有，表头按钮负责回调。
class CbrDataTable<T> extends StatelessWidget {
  const CbrDataTable({
    super.key,
    required this.columns,
    required this.rows,
    this.empty,
    this.sortKey,
    this.sortDescending = false,
    this.onSort,
    this.rowKey,
    this.density,
  });

  final List<CbrTableColumn<T>> columns;
  final List<T> rows;
  final Widget? empty;
  final String? sortKey;
  final bool sortDescending;
  final ValueChanged<String>? onSort;
  final String Function(T row)? rowKey;
  final double? density;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final CbrBreakpoint breakpoint =
        CbrBreakpointScope.maybeOf(context) ??
        CbrBreakpoint.fromWidth(MediaQuery.sizeOf(context).width);

    if (rows.isEmpty) {
      return empty ?? const SizedBox.shrink();
    }

    if (breakpoint.isCompact) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          for (var i = 0; i < rows.length; i++)
            Padding(
              padding: const EdgeInsets.only(bottom: CbrSpace.s3),
              child: _RowCard<T>(
                row: rows[i],
                columns: columns,
                index: i,
                total: rows.length,
              ),
            ),
        ],
      );
    }

    final List<CbrTableColumn<T>> visible = columns.where((c) {
      if (c.priority >= 3 && !breakpoint.atLeastExpanded) return false;
      if (c.priority >= 2 && !breakpoint.atLeastLarge) return false;
      return true;
    }).toList();

    final double rowHeight = density ?? breakpoint.tableRowHeight;
    final bool freezeFirst = breakpoint.atLeastExpanded;

    Widget headerCell(CbrTableColumn<T> column) => Expanded(
      flex: column.width == null ? 1 : 0,
      child: SizedBox(
        width: column.width,
        child: Semantics(
          header: true,
          child: CbrPressable(
            onPressed: onSort == null ? null : () => onSort!(column.key),
            semanticLabel:
                '${column.title}${sortKey == column.key ? (sortDescending ? '，已按降序排列' : '，已按升序排列') : ''}',
            minTapTarget: 0,
            borderRadius: CbrRadius.noneAll,
            child: Row(
              children: <Widget>[
                Flexible(
                  child: Text(
                    column.title,
                    overflow: TextOverflow.ellipsis,
                    style: CbrType.labelStrong.copyWith(
                      color: palette.textSecondary,
                    ),
                  ),
                ),
                if (sortKey == column.key)
                  Icon(
                    sortDescending
                        ? Icons.arrow_drop_down
                        : Icons.arrow_drop_up,
                    size: CbrIconSize.md,
                    color: palette.textSecondary,
                  ),
              ],
            ),
          ),
        ),
      ),
    );

    Widget dataCell(CbrTableColumn<T> column, T row, int index) => Expanded(
      flex: column.width == null ? 1 : 0,
      child: SizedBox(
        width: column.width,
        child: Align(alignment: column.align, child: column.cell(context, row)),
      ),
    );

    return Container(
      decoration: BoxDecoration(
        border: Border.all(
          color: palette.borderDefault,
          width: CbrBorder.hairline,
        ),
        borderRadius: CbrRadius.mdAll,
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: <Widget>[
          Container(
            height: rowHeight,
            color: palette.surfaceInset,
            padding: const EdgeInsets.symmetric(horizontal: CbrSpace.s3),
            child: Row(
              children: <Widget>[
                for (final column in visible) headerCell(column),
              ],
            ),
          ),
          Flexible(
            child: ListView.builder(
              shrinkWrap: true,
              itemCount: rows.length,
              itemBuilder: (context, index) {
                final row = rows[index];
                return Semantics(
                  label: '第 ${index + 1} 行，共 ${rows.length} 行',
                  child: Container(
                    height: rowHeight,
                    padding: const EdgeInsets.symmetric(
                      horizontal: CbrSpace.s3,
                    ),
                    decoration: BoxDecoration(
                      border: Border(
                        top: BorderSide(
                          color: palette.borderSubtle,
                          width: CbrBorder.hairline,
                        ),
                      ),
                    ),
                    child: Row(
                      children: <Widget>[
                        if (freezeFirst && visible.isNotEmpty) ...<Widget>[
                          dataCell(visible.first, row, index),
                          Container(
                            width: CbrBorder.hairline,
                            height: rowHeight,
                            color: palette.borderSubtle,
                          ),
                        ],
                        for (final column in visible.skip(freezeFirst ? 1 : 0))
                          dataCell(column, row, index),
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _RowCard<T> extends StatelessWidget {
  const _RowCard({
    required this.row,
    required this.columns,
    required this.index,
    required this.total,
  });

  final T row;
  final List<CbrTableColumn<T>> columns;
  final int index;
  final int total;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    return Semantics(
      label: '第 ${index + 1} 行，共 $total 行',
      child: Container(
        padding: const EdgeInsets.all(CbrSpace.s4),
        decoration: BoxDecoration(
          color: palette.surfaceBase,
          borderRadius: CbrRadius.mdAll,
          border: Border.all(
            color: palette.borderDefault,
            width: CbrBorder.hairline,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            for (var i = 0; i < columns.length; i++) ...<Widget>[
              if (i > 0) const SizedBox(height: CbrSpace.s2),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  SizedBox(
                    width: 96,
                    child: Text(
                      columns[i].title,
                      style: CbrType.label.copyWith(
                        color: palette.textSecondary,
                      ),
                    ),
                  ),
                  Expanded(child: columns[i].cell(context, row)),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}
