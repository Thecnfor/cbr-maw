import 'package:fl_chart/fl_chart.dart';
import 'package:material_ui/material_ui.dart';

import '../layout/breakpoints.dart';
import '../tokens/colors.dart';
import '../tokens/tokens.dart';

/// 一条图表系列。`colorIndex` 取 1..8，越界按色板循环（docs/06 §2.5）。
@immutable
class CbrSeries {
  const CbrSeries({
    required this.name,
    required this.points,
    this.colorIndex = 1,
    this.dashed = false,
  });

  final String name;
  final List<({double x, double y})> points;
  final int colorIndex;

  /// 色相用尽后换线型，保证黑白打印可区分（docs/06 §2.5）。
  final bool dashed;
}

/// 图表卡：图例可切换 + 数据表视图等价通道（docs/06 §6.2、docs/07 §3.5）。
///
/// 高度按容器宽度 `clamp(0.42 × 宽度, 200/220, 420/440)` 计算，不设固定尺寸。
class CbrChartCard extends StatefulWidget {
  const CbrChartCard({
    super.key,
    required this.title,
    required this.series,
    this.legendToggleable = true,
    this.empty,
    this.loading = false,
  });

  final String title;
  final List<CbrSeries> series;
  final bool legendToggleable;
  final Widget? empty;
  final bool loading;

  @override
  State<CbrChartCard> createState() => _CbrChartCardState();
}

class _CbrChartCardState extends State<CbrChartCard> {
  late final Set<int> _hidden = <int>{};
  bool _tableView = false;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    // 用自身内容宽度推导断点：图表可能被嵌在任何宽度的 surface 中，
    // 不假设外层一定放了 CbrLayoutBuilder。
    final CbrBreakpoint breakpoint =
        CbrBreakpointScope.maybeOf(context) ??
        CbrBreakpoint.fromWidth(MediaQuery.sizeOf(context).width);
    final visible = <int>[
      for (var i = 0; i < widget.series.length; i++)
        if (!_hidden.contains(i)) i,
    ];

    return Container(
      padding: const EdgeInsets.all(CbrSpace.s5),
      decoration: BoxDecoration(
        color: palette.surfaceBase,
        borderRadius: CbrRadius.lgAll,
        border: Border.all(
          color: palette.borderDefault,
          width: CbrBorder.hairline,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Text(
                  widget.title,
                  style: CbrType.title.copyWith(color: palette.textPrimary),
                ),
              ),
              Tooltip(
                message: _tableView ? '切换到图表' : '切换到数据表',
                child: IconButton(
                  onPressed: () => setState(() => _tableView = !_tableView),
                  icon: Icon(
                    _tableView ? Icons.show_chart : Icons.table_rows,
                    size: CbrIconSize.md,
                    color: palette.textSecondary,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: CbrSpace.s3),
          if (widget.loading)
            SizedBox(
              height: breakpoint.chartHeight(320),
              child: const Center(child: CircularProgressIndicator()),
            )
          else if (widget.series.isEmpty || visible.isEmpty)
            widget.empty ?? const SizedBox(height: 160)
          else if (_tableView)
            _ChartDataTable(series: widget.series, visible: visible)
          else
            LayoutBuilder(
              builder: (context, constraints) {
                final double height = breakpoint.chartHeight(
                  constraints.maxWidth,
                );
                return SizedBox(
                  height: height,
                  child: Semantics(
                    label: _semanticsLabel(widget.series),
                    child: LineChart(
                      LineChartData(
                        minX: _minX(),
                        maxX: _maxX(),
                        gridData: FlGridData(
                          show: true,
                          drawVerticalLine: false,
                          getDrawingHorizontalLine: (_) => FlLine(
                            color: palette.borderSubtle,
                            strokeWidth: CbrBorder.hairline,
                          ),
                        ),
                        borderData: FlBorderData(
                          show: true,
                          border: Border(
                            left: BorderSide(
                              color: palette.borderStrong,
                              width: CbrBorder.hairline,
                            ),
                            bottom: BorderSide(
                              color: palette.borderStrong,
                              width: CbrBorder.hairline,
                            ),
                          ),
                        ),
                        titlesData: FlTitlesData(
                          topTitles: const AxisTitles(
                            sideTitles: SideTitles(showTitles: false),
                          ),
                          rightTitles: const AxisTitles(
                            sideTitles: SideTitles(showTitles: false),
                          ),
                          leftTitles: AxisTitles(
                            sideTitles: SideTitles(
                              showTitles: true,
                              reservedSize: 40,
                              getTitlesWidget: (value, meta) => Text(
                                value.toStringAsFixed(0),
                                style: CbrType.caption.copyWith(
                                  color: palette.textSecondary,
                                ),
                              ),
                            ),
                          ),
                          bottomTitles: AxisTitles(
                            sideTitles: SideTitles(
                              showTitles: true,
                              reservedSize: 24,
                              getTitlesWidget: (value, meta) => Text(
                                value.toStringAsFixed(0),
                                style: CbrType.caption.copyWith(
                                  color: palette.textSecondary,
                                ),
                              ),
                            ),
                          ),
                        ),
                        lineBarsData: <LineChartBarData>[
                          for (final index in visible)
                            LineChartBarData(
                              spots: <FlSpot>[
                                for (final point in widget.series[index].points)
                                  FlSpot(point.x, point.y),
                              ],
                              color: palette.vizColor(
                                widget.series[index].colorIndex,
                              ),
                              barWidth: 2,
                              isCurved: false,
                              dashArray: widget.series[index].dashed
                                  ? <int>[6, 4]
                                  : null,
                              dotData: const FlDotData(show: false),
                            ),
                        ],
                      ),
                    ),
                  ),
                );
              },
            ),
          if (!_tableView && widget.series.length > 1) ...<Widget>[
            const SizedBox(height: CbrSpace.s3),
            Wrap(
              spacing: CbrSpace.s4,
              runSpacing: CbrSpace.s2,
              children: <Widget>[
                for (var i = 0; i < widget.series.length; i++)
                  _LegendItem(
                    series: widget.series[i],
                    hidden: _hidden.contains(i),
                    onTap: widget.legendToggleable
                        ? () => setState(() {
                            if (!_hidden.remove(i)) _hidden.add(i);
                          })
                        : null,
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  double _minX() =>
      widget.series
          .expand((s) => s.points)
          .fold<double?>(
            null,
            (min, p) => min == null || p.x < min ? p.x : min,
          ) ??
      0;

  double _maxX() =>
      widget.series
          .expand((s) => s.points)
          .fold<double?>(
            null,
            (max, p) => max == null || p.x > max ? p.x : max,
          ) ??
      1;

  String _semanticsLabel(List<CbrSeries> series) {
    final parts = series.map((s) {
      final values = s.points.map((p) => p.y);
      final max = values.reduce((a, b) => a > b ? a : b);
      final min = values.reduce((a, b) => a < b ? a : b);
      return '${s.name} 最高 ${max.toStringAsFixed(1)}，最低 ${min.toStringAsFixed(1)}';
    });
    return '${widget.title}折线图，${parts.join('；')}';
  }
}

class _LegendItem extends StatelessWidget {
  const _LegendItem({required this.series, required this.hidden, this.onTap});

  final CbrSeries series;
  final bool hidden;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final Color color = palette.vizColor(series.colorIndex);
    return Semantics(
      button: onTap != null,
      selected: !hidden,
      label: '${series.name}，${hidden ? '已隐藏' : '已显示'}',
      child: GestureDetector(
        onTap: onTap,
        child: Opacity(
          opacity: hidden ? 0.4 : 1,
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Container(width: 12, height: 2, color: color),
              const SizedBox(width: CbrSpace.s2),
              Text(
                series.name,
                style: CbrType.caption.copyWith(color: palette.textSecondary),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 图表的非视觉等价通道（docs/06 §2.5、docs/07 §3.5）。
class _ChartDataTable extends StatelessWidget {
  const _ChartDataTable({required this.series, required this.visible});

  final List<CbrSeries> series;
  final List<int> visible;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        headingTextStyle: CbrType.labelStrong.copyWith(
          color: palette.textSecondary,
        ),
        dataTextStyle: CbrType.numericSmall.copyWith(
          color: palette.textPrimary,
        ),
        columns: <DataColumn>[
          const DataColumn(label: Text('x')),
          for (final index in visible)
            DataColumn(label: Text(series[index].name)),
        ],
        rows: <DataRow>[
          for (var i = 0; i < series[visible.first].points.length; i++)
            DataRow(
              cells: <DataCell>[
                DataCell(
                  Text(series[visible.first].points[i].x.toStringAsFixed(0)),
                ),
                for (final index in visible)
                  DataCell(
                    Text(
                      i < series[index].points.length
                          ? series[index].points[i].y.toStringAsFixed(2)
                          : '—',
                    ),
                  ),
              ],
            ),
        ],
      ),
    );
  }
}
