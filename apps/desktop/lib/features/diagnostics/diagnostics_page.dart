import 'dart:io';

import '../../app/ui.dart';

import '../../app/app_scope.dart';
import '../../app/theme/tokens.dart';
import '../../app/widgets/common.dart';
import '../../app/widgets/states.dart';
import '../../core/clock.dart';

/// 诊断（docs/02 F1-6）：版本、平台、数据集状态、内核状态、错误日志。
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
