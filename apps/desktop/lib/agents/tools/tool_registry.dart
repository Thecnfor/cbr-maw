/// 确定性工具调用与权限矩阵（docs/03 §1.5 / §2.3；contracts/README.md §4）。
///
/// 两套入口刻意区分：
/// - [ToolRegistry.run] 带权限矩阵，default_deny；越权**绝不执行**；
/// - [ToolRegistry.recompute] 绕过权限，仅供核验/仲裁的权威重算。
///
/// 工具执行在 Rust kernel（`tools.invoke`），本层只做鉴权与证据构造；
/// 传输由 [ToolInvoker] 注入（sidecar 客户端或测试桩）。
library;

import 'package:cbr_maw_contracts/contracts_dart.dart'
    show ToolSpec, toolRegistry;

import '../blackboard/evidence_blackboard.dart';
import '../models/domain.dart';
import '../roles/role_config.dart';

/// 工具执行结果。
final class ToolOutcome {
  /// 创建结果。
  const ToolOutcome({
    required this.ok,
    this.evidence,
    this.error,
    this.denied = false,
  });

  /// 是否成功。
  final bool ok;

  /// 产出的证据（ok 时非空）。
  final Evidence? evidence;

  /// 错误说明。
  final String? error;

  /// 是否越权被拒。
  final bool denied;
}

/// 工具执行传输（注入实现：sidecar / 测试桩）。
abstract interface class ToolInvoker {
  /// 调用确定性工具，返回结构化输出（含 value/unit/payload）。
  Future<ToolInvocation> invoke({
    required String tool,
    required String asOf,
    required Map<String, Object?> params,
  });
}

/// 一次工具调用的原始返回。
final class ToolInvocation {
  /// 创建返回。
  const ToolInvocation({
    required this.tool,
    required this.version,
    required this.value,
    this.unit,
    this.payload = const {},
    this.title,
    this.summary = '',
  });

  /// 工具名。
  final String tool;

  /// 版本。
  final String version;

  /// 主数值。
  final double? value;

  /// 单位。
  final String? unit;

  /// 结构化载荷。
  final Map<String, Object?> payload;

  /// 标题。
  final String? title;

  /// 摘要。
  final String summary;
}

/// 工具未实现（零 Mock：显式失败，不编造数值）。
final class ToolUnavailable implements Exception {
  /// 创建异常。
  const ToolUnavailable(this.tool, this.reason);

  /// 工具名。
  final String tool;

  /// 原因。
  final String reason;

  @override
  String toString() => 'ToolUnavailable($tool): $reason';
}

/// 工具注册表 + 权限矩阵。
final class ToolRegistry {
  /// 创建注册表。
  ToolRegistry({
    required this.specs,
    required this.invoker,
    this.defaultDeny = true,
  });

  /// 角色规范（tool_permissions 唯一来源）。
  final Map<RoleId, RoleSpec> specs;

  /// 执行传输。
  final ToolInvoker invoker;

  /// 默认拒绝未知角色/工具。
  final bool defaultDeny;

  /// 越权审计（角色, 工具）。
  final List<(RoleId, String)> denials = [];

  /// 已注册工具名。
  Set<String> get names => {for (final spec in toolRegistry) spec.tool};

  /// 取工具注册信息（未知返回 null）。
  static ToolSpec? specOf(String tool) {
    for (final spec in toolRegistry) {
      if (spec.tool == tool) {
        return spec;
      }
    }
    return null;
  }

  /// 角色是否可调用某工具（default_deny）。
  bool allows(RoleId role, String tool) {
    if (defaultDeny) {
      final roleSpec = specs[role];
      final toolSpec = specOf(tool);
      if (roleSpec == null || toolSpec == null) {
        return false;
      }
      if (!toolSpec.allowsRole(role.wire)) {
        return false;
      }
      // 角色配置的工具白名单是第二道闸门。
      return roleSpec.allowsTool(tool);
    }
    return true;
  }

  /// 带权限矩阵的调用：越权 → 不执行，记审计。
  Future<ToolOutcome> run({
    required RoleId role,
    required String tool,
    required String asOf,
    Map<String, Object?> params = const {},
  }) async {
    if (!allows(role, tool)) {
      denials.add((role, tool));
      return const ToolOutcome(
        ok: false,
        denied: true,
        error: 'permission_denied',
      );
    }
    return _invoke(tool: tool, asOf: asOf, params: params);
  }

  /// 绕过权限的权威重算（仅核验/仲裁使用）。
  Future<ToolOutcome> recompute({
    required String tool,
    required String asOf,
    Map<String, Object?> params = const {},
  }) => _invoke(tool: tool, asOf: asOf, params: params);

  Future<ToolOutcome> _invoke({
    required String tool,
    required String asOf,
    required Map<String, Object?> params,
  }) async {
    final spec = specOf(tool);
    if (spec == null) {
      return const ToolOutcome(ok: false, error: 'unknown_tool');
    }
    final merged = {...spec.defaultParams, ...params};
    try {
      final result = await invoker.invoke(
        tool: tool,
        asOf: asOf,
        params: merged,
      );
      final inputsHash = sha256Hex(
        canonicalJson({
          'tool': result.tool,
          'version': result.version,
          'as_of': asOf,
          'params': merged,
        }),
      );
      final payload = {
        ...result.payload,
        'value': result.value,
        'unit': result.unit,
      };
      final evidence = Evidence(
        evidenceId: _evidenceId(result.tool, result.version, inputsHash),
        kind: EvidenceKind.tool,
        asOf: DateTime.parse(asOf.length == 10 ? asOf : asOf.substring(0, 10)),
        title: result.title ?? '${result.tool} 读数',
        summary: result.summary,
        payload: payload,
        unit: result.unit,
        value: result.value,
        source: const SourceRef(name: 'tools.invoke'),
        tool: ToolRef(
          name: result.tool,
          version: result.version,
          inputsHash: inputsHash,
        ),
        producedBy: result.tool,
        createdAt: DateTime.now().toUtc(),
        hash: sha256Hex(canonicalJson(payload)),
      );
      return ToolOutcome(ok: true, evidence: evidence);
    } on ToolUnavailable catch (error) {
      return ToolOutcome(ok: false, error: error.reason);
    }
  }

  /// `ev_` + sha256({tool, version, inputs_hash}) 前 16 位。
  static String _evidenceId(String tool, String version, String inputsHash) {
    final digest = sha256Hex(
      canonicalJson({
        'tool': tool,
        'version': version,
        'inputs_hash': inputsHash,
      }),
    );
    return 'ev_${digest.substring(0, 16)}';
  }
}
