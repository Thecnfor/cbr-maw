/// R5.1 六类核验（docs/03 §2.3；旧 `verification/verifier.py`）。
///
/// 覆盖：引文 / 泄漏 / 数值 / 权限 / 冲突 / 预算（任务卡口径），并保留 docs/03
/// 的 schema / unsupported 细分。
///
/// 通过判据：numericErrorRate == 0 && permissionViolations == 0
///           && leakageEvents == 0 && schemaErrors == 0。
/// 泄漏事件 > 0 → 核验不通过（硬错误）。
library;

import '../models/domain.dart';
import '../roles/role_config.dart';

/// 核验上下文。
final class VerificationContext {
  /// 创建上下文。
  const VerificationContext({
    required this.runId,
    required this.asOf,
    required this.cards,
    required this.evidenceIndex,
    required this.deniedToolCalls,
    this.conflicts = const [],
    this.budgetTruncated = false,
    this.budgetTripped = false,
    this.roleSpecs = const {},
    this.absTol = 1e-6,
    this.relTol = 1e-3,
  });

  /// run id。
  final String runId;

  /// 决策时点。
  final DateTime asOf;

  /// 子卡。
  final List<RiskCard> cards;

  /// 证据索引（id → 证据）。
  final Map<String, Evidence> evidenceIndex;

  /// 越权工具调用（角色, 工具）。
  final List<(RoleId, String)> deniedToolCalls;

  /// 冲突（含仲裁结果）。
  final List<Conflict> conflicts;

  /// 预算是否发生截断。
  final bool budgetTruncated;

  /// 是否触发熔断。
  final bool budgetTripped;

  /// 角色规范（用于信息域白名单校验）。
  final Map<RoleId, RoleSpec> roleSpecs;

  /// 数值绝对容差。
  final double absTol;

  /// 数值相对容差。
  final double relTol;
}

/// 运行六类核验。
VerificationReport verify(VerificationContext context) {
  var numericTotal = 0;
  var numericPassed = 0;
  var citationTotal = 0;
  var citationPassed = 0;
  var unsupported = 0;
  var leakage = 0;
  var permission = 0;
  var schemaErrors = 0;
  final issues = <VerificationIssue>[];

  // 冲突：未解决的事实/方向冲突必须被看见（偏好差异不算问题）。
  for (final conflict in context.conflicts) {
    if (conflict.type == ConflictType.preference || conflict.resolved) {
      continue;
    }
    issues.add(
      VerificationIssue(
        issueType: 'conflict',
        detail:
            '未解决冲突 ${conflict.conflictId}（${conflict.type.wire}）：${conflict.description}',
        severity: 'warning',
      ),
    );
  }

  // 预算：耗尽即降级为部分结论，必须可见（不阻塞，不伪造）。
  if (context.budgetTruncated || context.budgetTripped) {
    issues.add(
      VerificationIssue(
        issueType: 'budget',
        detail: context.budgetTripped
            ? '预算/时间熔断：本次研判提前收敛，结论为部分结论。'
            : '预算截断：部分工具调用或生成被裁剪，结论为部分结论。',
        severity: 'warning',
      ),
    );
  }

  // 权限：越权工具调用（工具未执行）。
  for (final (role, tool) in context.deniedToolCalls) {
    permission++;
    issues.add(
      VerificationIssue(
        issueType: 'permission',
        role: role,
        detail: '角色 ${role.wire} 越权调用工具 $tool（未执行）。',
        severity: 'error',
      ),
    );
  }

  // 泄漏：证据 as_of / release_time 晚于决策时点。
  final flagged = <String>{};
  for (final evidence in context.evidenceIndex.values) {
    final evidenceDate = _dateOnly(evidence.asOf);
    if (evidenceDate.isAfter(_dateOnly(context.asOf)) &&
        flagged.add(evidence.evidenceId)) {
      leakage++;
      issues.add(
        VerificationIssue(
          issueType: 'leakage',
          detail:
              '证据 ${evidence.evidenceId} 的 as_of=${_iso(evidence.asOf)} 晚于决策时点 ${_iso(context.asOf)}。',
          severity: 'error',
        ),
      );
    }
    for (final source in [evidence.source, ...evidence.citations]) {
      final release = source.releaseTime;
      if (release != null &&
          _dateOnly(release).isAfter(_dateOnly(context.asOf)) &&
          flagged.add('${evidence.evidenceId}:${source.name}')) {
        leakage++;
        issues.add(
          VerificationIssue(
            issueType: 'leakage',
            detail:
                '证据 ${evidence.evidenceId} 的来源 ${source.name} release_time=${release.toIso8601String()} 晚于决策时点。',
            severity: 'error',
          ),
        );
      }
    }
  }

  // 逐卡逐 claim：schema / citation / numeric / permission / unsupported。
  for (final card in context.cards) {
    final seenClaimIds = <String>{};
    for (final claim in card.claims) {
      // R4 已判 rejected 的主张不再是有效结论：继续核验它的数值只会
      // 把「仲裁已经否掉了」的草稿算成数值错误，反过来把正确的仲裁判成失败。
      if (claim.status == ClaimStatus.rejected) {
        continue;
      }
      if (claim.claimId.isEmpty) {
        schemaErrors++;
        issues.add(
          VerificationIssue(
            issueType: 'schema',
            role: card.role,
            detail: '存在缺少 claim_id 的主张。',
            severity: 'error',
          ),
        );
      } else if (!seenClaimIds.add(claim.claimId)) {
        schemaErrors++;
        issues.add(
          VerificationIssue(
            issueType: 'schema',
            role: card.role,
            claimId: claim.claimId,
            detail: 'claim_id 重复：${claim.claimId}。',
            severity: 'error',
          ),
        );
      }
      if (claim.role != card.role) {
        schemaErrors++;
        issues.add(
          VerificationIssue(
            issueType: 'schema',
            role: card.role,
            claimId: claim.claimId,
            detail: '主张角色与卡片角色不一致。',
            severity: 'error',
          ),
        );
      }

      // citation
      if (claim.evidenceIds.isEmpty) {
        unsupported++;
        issues.add(
          VerificationIssue(
            issueType: 'unsupported',
            role: card.role,
            claimId: claim.claimId,
            detail: '主张 ${claim.claimId} 未绑定任何证据，属于无依据断言。',
            severity: 'warning',
          ),
        );
      } else {
        citationTotal++;
        final problems = <String>[];
        for (final evidenceId in claim.evidenceIds) {
          final evidence = context.evidenceIndex[evidenceId];
          if (evidence == null) {
            problems.add('引用的证据不存在：$evidenceId');
            continue;
          }
          if (evidence.kind == EvidenceKind.kb) {
            final chunkId =
                evidence.source.chunkId ??
                evidence.citations
                    .map((c) => c.chunkId)
                    .whereType<String>()
                    .firstOrNull;
            final publish =
                evidence.source.releaseTime ??
                evidence.citations
                    .map((c) => c.releaseTime)
                    .whereType<DateTime>()
                    .firstOrNull;
            if (chunkId == null || chunkId.isEmpty) {
              problems.add('KB 证据 $evidenceId 缺少 chunk_id');
            }
            if (publish == null) {
              problems.add('KB 证据 $evidenceId 缺少 publish_time');
            } else if (_dateOnly(publish).isAfter(_dateOnly(context.asOf))) {
              problems.add('KB 证据 $evidenceId 的 publish_time 晚于 as_of');
            }
          }
        }
        if (problems.isEmpty) {
          citationPassed++;
        } else {
          for (final problem in problems) {
            issues.add(
              VerificationIssue(
                issueType: 'citation',
                role: card.role,
                claimId: claim.claimId,
                detail: problem,
                severity: 'error',
              ),
            );
          }
        }
      }

      // numeric：claim 数值与所绑 tool/signal 证据在容差内一致。
      if (claim.claimType == ClaimType.numeric && claim.value != null) {
        final candidates = claim.evidenceIds
            .map((id) => context.evidenceIndex[id])
            .whereType<Evidence>()
            .where(
              (e) =>
                  (e.kind == EvidenceKind.tool ||
                      e.kind == EvidenceKind.signal) &&
                  e.value != null,
            )
            .toList();
        if (candidates.isNotEmpty) {
          numericTotal++;
          final matched = candidates.any(
            (e) => _numbersMatch(
              claim.value!,
              e.value!,
              context.absTol,
              context.relTol,
            ),
          );
          if (matched) {
            numericPassed++;
          } else {
            issues.add(
              VerificationIssue(
                issueType: 'numeric',
                role: card.role,
                claimId: claim.claimId,
                detail: '主张数值 ${claim.value} 与所绑工具证据不一致。',
                severity: 'error',
              ),
            );
          }
        }
      }

      // permission：claim 引用了角色信息域外的证据。
      final role = card.role;
      for (final evidenceId in claim.evidenceIds) {
        final evidence = context.evidenceIndex[evidenceId];
        if (evidence == null) {
          continue;
        }
        final domain = evidence.payload['domain'] as String?;
        final spec = context.roleSpecs[role];
        if (domain != null && spec != null && !spec.allowsDomain(domain)) {
          permission++;
          issues.add(
            VerificationIssue(
              issueType: 'permission',
              role: role,
              claimId: claim.claimId,
              detail: '主张引用了角色 ${role.wire} 信息域外的证据域 $domain。',
              severity: 'error',
            ),
          );
        }
      }
    }
  }

  final numericErrorRate = numericTotal == 0
      ? 0.0
      : (numericTotal - numericPassed) / numericTotal;
  final passed =
      numericErrorRate == 0 &&
      permission == 0 &&
      leakage == 0 &&
      schemaErrors == 0;

  return VerificationReport(
    runId: context.runId,
    numericChecksTotal: numericTotal,
    numericChecksPassed: numericPassed,
    citationChecksTotal: citationTotal,
    citationChecksPassed: citationPassed,
    unsupportedClaims: unsupported,
    permissionViolations: permission,
    leakageEvents: leakage,
    schemaErrors: schemaErrors,
    issues: issues,
    passed: passed,
  );
}

bool _numbersMatch(double a, double b, double absTol, double relTol) {
  final diff = (a - b).abs();
  if (diff <= absTol) {
    return true;
  }
  final scale = a.abs() > b.abs() ? a.abs() : b.abs();
  return scale > 0 && diff / scale <= relTol;
}

DateTime _dateOnly(DateTime value) =>
    DateTime.utc(value.year, value.month, value.day);

String _iso(DateTime value) => value.toIso8601String().substring(0, 10);
