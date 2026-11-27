import 'dart:io';

import '../../app/ui.dart';

import '../../app/app_scope.dart';
import '../../app/theme/tokens.dart';
import '../../app/widgets/common.dart';
import '../../app/widgets/states.dart';
import '../../agents/signals/kernel_reflection.dart';
import '../../app/app_state.dart';
import '../../core/clock.dart';

/// 诊断（docs/02 F1-6）：版本、平台、数据集状态、内核状态、错误日志、
/// 预警效能复盘（`X-AlertAgent` HLR）。
final class DiagnosticsPage extends StatelessWidget {
  /// 创建页面。
  const DiagnosticsPage({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    final handshake = state.supervisor.handshake;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const PageHeader(title: '诊断', subtitle: '一页看完版本、内核、数据集与本次会话审计；每项可复制'),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(
              Tokens.space5,
              0,
              Tokens.space5,
              Tokens.space8,
            ),
            children: [
              SectionCard(
                title: '应用与平台',
                child: Column(
                  children: [
                    const KeyValueRow(label: '应用版本', value: '0.1.0'),
                    KeyValueRow(label: '平台', value: Platform.operatingSystem),
                    KeyValueRow(
                      label: '可执行文件',
                      value: Platform.resolvedExecutable,
                    ),
                    KeyValueRow(
                      label: '当前时刻',
                      value: Clock.display(Clock.asOfNow()),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: Tokens.space4),
              SectionCard(
                title: '本地内核',
                child: Column(
                  children: [
                    KeyValueRow(label: '状态', value: state.kernelState.label),
                    KeyValueRow(
                      label: '内核版本',
                      value: handshake?.version ?? '未握手',
                    ),
                    KeyValueRow(
                      label: '契约版本',
                      value:
                          handshake?.contractVersion ?? state.config.timezone,
                    ),
                    KeyValueRow(
                      label: 'schema 版本',
                      value: handshake?.schemaVersion.toString() ?? '—',
                    ),
                    KeyValueRow(
                      label: '能力',
                      value: handshake == null
                          ? '—'
                          : handshake.capabilities.join('、'),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: Tokens.space4),
              SectionCard(
                title: '数据集',
                child: Column(
                  children: [
                    KeyValueRow(
                      label: '数据模式',
                      value: state.config.syntheticDefault
                          ? 'SYNTHETIC 仿真'
                          : '真实抓取',
                    ),
                    KeyValueRow(label: '工作区', value: state.paths.workspacePath),
                    KeyValueRow(label: '可写根', value: state.paths.dataHome),
                    KeyValueRow(label: '日志目录', value: state.paths.logsDir),
                  ],
                ),
              ),
              const SizedBox(height: Tokens.space4),
              SectionCard(
                title: '本次会话审计',
                child: state.auditEvents.isEmpty
                    ? const Text('尚无审计事件。')
                    : Column(
                        children: [
                          for (final event in state.auditEvents.take(20))
                            ListRow(
                              title: '${event.type} · ${event.tool}',
                              subtitle:
                                  '${event.actor} · ${event.outcome} · '
                                  '${Clock.display(event.ts)}',
                            ),
                        ],
                      ),
              ),
              const SizedBox(height: Tokens.space4),
              _PerformanceSection(state: state),
              const SizedBox(height: Tokens.space4),
              const InlineBanner(
                message: '诊断信息不包含密钥明文。导出前请确认不含个人路径后分享。',
                tone: BannerTone.info,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// 预警效能复盘（`X-AlertAgent` HLR）：过去报得准不准。
///
/// 这是产品里唯一能回答「我们的预警有没有用」的地方——浅层反思只回答
/// 「像历史上哪天」，不回答对错。
final class _PerformanceSection extends StatefulWidget {
  const _PerformanceSection({required this.state});

  final AppState state;

  @override
  State<_PerformanceSection> createState() => _PerformanceSectionState();
}

class _PerformanceSectionState extends State<_PerformanceSection> {
  ReflectionPerformance? _result;
  String? _error;
  bool _loading = false;

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await KernelDeepReflection(widget.state.supervisor).read(
        DateTime.now().toUtc(),
      );
      if (!mounted) return;
      setState(() {
        _result = result;
        _error = result == null ? '历史不足或信号未计算，暂无可用复盘' : null;
        _loading = false;
      });
    } on Object catch (e) {
      if (!mounted) return;
      setState(() {
        _error = '复盘失败：$e';
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = _result;
    return SectionCard(
      title: '预警效能复盘',
      trailing: TextButton(
        onPressed: _loading ? null : _load,
        child: Text(_loading ? '复盘中…' : '复盘'),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_error != null)
            Text(_error!, style: Theme.of(context).textTheme.bodySmall)
          else if (r == null)
            const Text('点「复盘」统计历史预警的命中与漏报。')
          else ...[
            Wrap(
              spacing: Tokens.space3,
              runSpacing: Tokens.space3,
              children: [
                MetricTile(
                  label: '精确率',
                  value: r.precision == null
                      ? '不可计算'
                      : r.precision!.toStringAsFixed(3),
                  hint: '报警中真的进入压力区的比例',
                ),
                MetricTile(
                  label: '召回率',
                  value: r.recall == null
                      ? '不可计算'
                      : r.recall!.toStringAsFixed(3),
                  hint: '真实压力中被提前报出的比例',
                  tone: (r.recall ?? 1) < 0.6 ? BannerTone.warn : null,
                ),
                MetricTile(
                  label: '相对基准增益',
                  value: r.lift == null ? '不可计算' : '${r.lift!.toStringAsFixed(2)}×',
                  hint: '>1 才说明比「一直报警」强',
                  tone: (r.lift ?? 1) <= 1.05 ? BannerTone.warn : BannerTone.ok,
                ),
                MetricTile(
                  label: '漏报 / 误报',
                  value: '${r.missed} / ${r.falseAlarms}',
                  hint: '可评估 ${r.evaluableDays} 个时点',
                ),
              ],
            ),
            const SizedBox(height: Tokens.space3),
            Text(
              '只统计事后窗口已走完的时点；复盘结果不写回当期定级。',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ],
      ),
    );
  }
}
