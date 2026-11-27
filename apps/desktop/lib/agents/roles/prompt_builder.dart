/// 提示词装配（docs/03 §1.4）：角色模板 + 通用规则，按 RoleSpec 渲染占位符。
///
/// 模板来自 `lib/agents/prompts/*.md`（由 `configs/prompts/` 迁移，语义不变）。
library;

import 'dart:convert';

import 'asset_source.dart';
import '../models/domain.dart';
import '../roles/role_config.dart';

/// 角色提示词渲染器。
final class PromptBuilder {
  PromptBuilder._(this._templates);

  /// 从资源源加载全部模板（应用传 `BundleAssetSource`，CLI 传 `FileAssetSource`）。
  static Future<PromptBuilder> load(AssetSource source) async {
    const names = [
      'common_rules',
      'regulator',
      'investor',
      'financing',
      'cross_validation',
      'single_agent',
    ];
    final templates = <String, String>{};
    for (final name in names) {
      templates[name] = await source.read('lib/agents/prompts/$name.md');
    }
    return PromptBuilder._(templates);
  }

  /// 直接用模板文本构造（测试用）。
  factory PromptBuilder.fromTemplates(Map<String, String> templates) =>
      PromptBuilder._({...templates});

  final Map<String, String> _templates;

  /// 渲染角色 system prompt。
  String renderRole(RoleId role) {
    final template = _templates[role.wire];
    if (template == null) {
      throw StateError('缺少角色模板 ${role.wire}.md');
    }
    return template;
  }

  /// 渲染角色 system prompt（注入 RoleSpec 字段）。
  String renderRoleWithSpec(RoleSpec spec) {
    final template = renderRole(spec.role);
    final rendered = _fill(template, spec.renderFields);
    return '$rendered\n\n${_templates['common_rules'] ?? ''}';
  }

  /// 渲染交叉验证 prompt。
  String renderCrossValidation(RoleSpec spec) => _fill(
    _templates['cross_validation'] ?? '',
    {
      'display_name': spec.displayName,
      'tool_permissions': spec.toolPermissions.map((t) => '- $t').join('\n'),
      'forbidden_actions': spec.forbiddenActions.map((f) => '- $f').join('\n'),
    },
  );

  /// 渲染单智能体基线 prompt（三主体目标函数）。
  String renderSingleAgent(Map<RoleId, RoleSpec> specs) =>
      _fill(_templates['single_agent'] ?? '', {
        'regulator_objective': specs[RoleId.regulator]?.objective ?? '',
        'investor_objective': specs[RoleId.investor]?.objective ?? '',
        'financing_objective': specs[RoleId.financing]?.objective ?? '',
      });

  /// 通用输出规则。
  String get commonRules => _templates['common_rules'] ?? '';

  String _fill(String template, Map<String, String> fields) {
    var result = template;
    for (final entry in fields.entries) {
      result = result.replaceAll('{{${entry.key}}}', entry.value);
    }
    return result;
  }
}

/// 构造 user prompt 的证据包（结构化字段注入，非文本拼接）。
String buildEvidencePrompt({
  required DateTime asOf,
  required String task,
  required List<Evidence> evidence,
  List<Evidence> peerFacts = const [],
}) {
  final packet = {
    'as_of': asOf.toIso8601String().substring(0, 10),
    'task': task,
    'evidence': [
      for (final item in evidence)
        {
          'evidence_id': item.evidenceId,
          'kind': item.kind.wire,
          'title': item.title,
          'summary': item.summary,
          'value': item.value,
          'unit': item.unit,
          'as_of': item.asOf.toIso8601String().substring(0, 10),
          'source': item.source.toJson(),
          if (item.tool != null) 'tool': item.tool!.toJson(),
        },
    ],
    if (peerFacts.isNotEmpty)
      'peer_facts': [
        for (final item in peerFacts)
          {
            'evidence_id': item.evidenceId,
            'kind': item.kind.wire,
            'title': item.title,
            'value': item.value,
            'unit': item.unit,
            'as_of': item.asOf.toIso8601String().substring(0, 10),
          },
      ],
  };
  return '证据包（只能引用下列 evidence_id）：\n${jsonEncode(packet)}';
}
