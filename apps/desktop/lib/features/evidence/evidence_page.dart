import 'dart:convert';

import 'package:cbr_maw_contracts/contracts_dart.dart';
import 'package:cbr_maw_design_system/cbr_maw_design_system.dart'
    show CbrEvidenceCard;
import 'package:flutter/services.dart' show Clipboard, ClipboardData;

import '../../app/app_state.dart';
import '../../app/routes.dart';
import '../../app/shell/app_shell.dart';
import '../../app/theme/tokens.dart';
import '../../app/ui.dart';
import '../../app/widgets/common.dart';
import '../../app/widgets/states.dart';
import '../../core/clock.dart';
import '../../core/errors.dart';

/// 证据详情（docs/02 F5-3）：原文片段、发布时间、来源、定位符、时点、
/// 工具版本与输入哈希。
final class EvidencePage extends StatefulWidget {
  /// 创建页面。
  const EvidencePage({
    required this.state,
    required this.evidenceId,
    super.key,
  });

  /// 应用状态。
  final AppState state;

  /// 证据 ID。
  final String evidenceId;

  @override
  State<EvidencePage> createState() => _EvidencePageState();
}

class _EvidencePageState extends State<EvidencePage> {
  Future<_EvidenceView>? _future;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() {
    setState(() {
      _future = _load();
    });
  }

  Future<_EvidenceView> _load() async {
    // 首选本次会话的工具证据索引：工具版本与输入哈希都在里面。
    final session = widget.state.toolEvidence[widget.evidenceId];
    if (session != null) {
      return _EvidenceView(
        result: null,
        fields: {
          'evidence_id': session.evidenceId,
          'tool': session.tool,
          'version': session.version,
          'inputs_hash': session.inputsHash,
          'hash': session.hash,
          'as_of': session.asOf,
          'value': session.value,
          'unit': session.unit,
          'params': session.params,
          'source_id': '本次会话的工具调用',
          // 工具读数明细（维度/窗口端点/新鲜度）：契约此前丢弃了它，
          // 导致证据页只能看到主数值，看不到「数据截至哪天」。
          if (session.data != null) 'data': session.data,
        },
      );
    }
    // `audit_events` 视图不支持按 evidence_id 过滤（契约只给 event_type /
    // role / tool_name / start / end）。按时间取最近审计，再在本地按证据 ID
    // 精确匹配；匹配不到就显式说明，不编造字段。
    final result = await widget.state.repository.query(
      view: DbView.auditEvents,
      asOf: Clock.asOfNow(),
      limit: 500,
    );
    for (final row in result.rows) {
      final map = <String, Object?>{
        for (var i = 0; i < result.columns.length && i < row.length; i++)
          result.columns[i]: row[i],
      };
      if (!_matches(map, widget.evidenceId)) {
        continue;
      }
      // detail 是 JSON 字符串：解开后并入字段（工具证据的
      // inputs_hash / hash / version / as_of 都在里面）。
      final detail = map['detail'];
      if (detail is String) {
        try {
          final decoded = jsonDecode(detail);
          if (decoded is Map) {
            map['detail'] = decoded;
            for (final entry in decoded.entries) {
              map.putIfAbsent('${entry.key}', () => entry.value);
            }
          }
        } on FormatException {
          // detail 不是 JSON：保留原文，不编造字段。
        }
      }
      return _EvidenceView(result: result, fields: map);
    }
    return _EvidenceView(result: result);
  }

  /// 证据 ID 可能出现在 `evidence_id` 列、`detail.evidence_id` 或 detail JSON 文本里。
  static bool _matches(Map<String, Object?> row, String id) {
    if (row['evidence_id']?.toString() == id) {
      return true;
    }
    final detail = row['detail'];
    if (detail is Map) {
      if (detail['evidence_id']?.toString() == id) {
        return true;
      }
    } else if (detail is String && detail.contains(id)) {
      return true;
    }
    return false;
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        PageHeader(
          title: '证据详情',
          subtitle: widget.evidenceId,
          actions: [
            OutlinedButton.icon(
              onPressed: () => AppShellNavigator.go(Routes.riskCards),
              icon: const Icon(Icons.arrow_back, size: 16),
              label: const Text('返回风险卡'),
            ),
          ],
        ),
        Expanded(
          child: FutureBuilder<_EvidenceView>(
            future: _future,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Center(child: CircularProgressIndicator());
              }
              if (snapshot.hasError) {
                final error = snapshot.error;
                final appError = error is AppError ? error : null;
                return ErrorStateView(
                  what: '证据读取失败',
                  why: appError?.why ?? '$error',
                  next: appError?.next ?? '可稍后重试；若持续失败请查看诊断页',
                  onRetry: _reload,
                );
              }
              final view = snapshot.data;
              final fields = view?.fields;
              if (fields == null) {
                return EmptyState(
                  title: '未找到该证据',
                  message:
                      '${widget.evidenceId} 在本地库中没有对应记录。'
                      '可能已被移除，或该证据来自其他工作区。',
                  icon: Icons.search_off,
                  actionLabel: '返回风险卡',
                  onAction: () => AppShellNavigator.go(Routes.riskCards),
                );
              }
              return ListView(
                padding: const EdgeInsets.fromLTRB(
                  Tokens.space5,
                  0,
                  Tokens.space5,
                  Tokens.space8,
                ),
                children: [
                  SectionCard(
                    title: '来源与定位',
                    child: Column(
                      children: [
                        KeyValueRow(
                          label: '来源',
                          value: fields['source_id']?.toString() ?? '未登记来源',
                        ),
                        // 原文片段用证据卡（长文本可展开），而不是塞进
                        // KeyValueRow 的一行里。
                        CbrEvidenceCard(
                          excerpt: fields['text']?.toString() ?? '该证据不含原文片段',
                          sourceName:
                              fields['source_id']?.toString() ?? '未登记来源',
                          timestamp: Clock.display(
                            fields['published_at']?.toString() ??
                                fields['as_of']?.toString(),
                          ),
                          title: fields['locator']?.toString(),
                        ),
                        KeyValueRow(
                          label: '定位符',
                          value: fields['locator']?.toString() ?? '无定位符',
                        ),
                        KeyValueRow(
                          label: '发布时间',
                          value: Clock.display(
                            fields['published_at']?.toString(),
                          ),
                        ),
                        KeyValueRow(
                          label: '时点',
                          value: Clock.display(fields['as_of']?.toString()),
                        ),
                        if (fields['value'] != null)
                          KeyValueRow(
                            label: '数值',
                            value:
                                '${fields['value']}'
                                '${fields['unit'] == null ? '' : ' ${fields['unit']}'}',
                          ),
                        KeyValueRow(
                          label: '状态',
                          value: fields['status']?.toString() ?? '有效（未被质疑或推翻）',
                        ),
                        if (fields['status_reason'] != null)
                          KeyValueRow(
                            label: '状态原因',
                            value: fields['status_reason'].toString(),
                          ),
                      ],
                    ),
                  ),
                  if (fields['data'] is Map) ...[
                    const SizedBox(height: Tokens.space4),
                    SectionCard(
                      title: '工具读数明细',
                      child: Column(
                        children: [
                          for (final entry
                              in (fields['data']! as Map).entries.take(12))
                            KeyValueRow(
                              label: '${entry.key}',
                              value: _formatField(entry.value),
                            ),
                        ],
                      ),
                    ),
                  ],
                  const SizedBox(height: Tokens.space4),
                  SectionCard(
                    title: '可重算哈希',
                    child: Column(
                      children: [
                        KeyValueRow(
                          label: '工具',
                          value: fields['tool']?.toString() ?? '—',
                        ),
                        KeyValueRow(
                          label: '工具版本',
                          value: fields['version']?.toString() ?? '—',
                        ),
                        _HashRow(
                          label: '输入哈希',
                          value: fields['inputs_hash']?.toString(),
                        ),
                        _HashRow(
                          label: '证据哈希',
                          value: fields['hash']?.toString(),
                        ),
                        _HashRow(
                          label: '证据 ID',
                          value: fields['evidence_id']?.toString(),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: Tokens.space3),
                  const InlineBanner(
                    message:
                        '哈希可重算：相同入参与时点两次调用必须得到同一证据 ID。'
                        '如与旧系统不一致，请在诊断页导出对照。',
                    tone: BannerTone.info,
                  ),
                ],
              );
            },
          ),
        ),
      ],
    );
  }
}

final class _EvidenceView {
  const _EvidenceView({required this.result, this.fields});

  /// 命中的查询结果（会话内证据时为 null）。
  final DbQueryResult? result;

  /// 字段（未命中为 null → 渲染「未找到」）。
  final Map<String, Object?>? fields;
}

/// 可复制的哈希行（长串等宽显示 + 复制按钮）。
final class _HashRow extends StatelessWidget {
  const _HashRow({required this.label, required this.value});

  final String label;
  final String? value;

  @override
  Widget build(BuildContext context) {
    final text = value;
    if (text == null || text.isEmpty) {
      return KeyValueRow(label: label, value: '—（未登记）');
    }
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 132,
            child: Text(
              label,
              style: TextStyle(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          ),
          Expanded(
            child: SelectableText(
              text,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
            ),
          ),
          IconButton(
            tooltip: '复制$label',
            iconSize: 16,
            visualDensity: VisualDensity.compact,
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: text));
              if (context.mounted) {
                ScaffoldMessenger.of(context)
                    .showSnackBar(SnackBar(content: Text('已复制$label')));
              }
            },
            icon: const Icon(Icons.copy_outlined),
          ),
        ],
      ),
    );
  }
}

/// 把工具读数里的值格式化为可读文本（嵌套结构折叠成一行 JSON）。
String _formatField(Object? value) {
  if (value == null) {
    return '—（缺失）';
  }
  if (value is num) {
    return value is double
        ? value.toStringAsFixed(value.abs() < 1 ? 6 : 4)
        : '$value';
  }
  if (value is String) {
    return value;
  }
  if (value is List) {
    return value.isEmpty ? '（空）' : value.map((e) => '$e').join('、');
  }
  if (value is Map) {
    return jsonEncode(value);
  }
  return '$value';
}
