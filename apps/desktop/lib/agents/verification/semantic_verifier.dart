/// JEV 语义核验（R5.3，ADR-010 §1、docs/01 §2.2）。
///
/// 六类核验里的「语义」一类：确定性能验证数值与引文，但验不了
/// 「这段话是否真的支持这个结论」。JEV 是裁判（不是生成者），
/// 只出 `supported / partially / unsupported` 三选一。
///
/// 零 Mock 严格模式：
/// - 裁判不可用 → 返回 `available=false` 且**不产出置信度**，界面明示
///   「未使用模型判断」；
/// - 绝不把规则模板伪装成裁判结论。
library;

import '../llm/llm_channel.dart';
import '../models/domain.dart';

/// 单条 claim 的语义核验结果。
final class SemanticCheck {
  /// 创建结果。
  const SemanticCheck({
    required this.claimId,
    required this.verdict,
    this.confidence,
    this.reason = '',
  });

  /// claim id。
  final String claimId;

  /// 判定：`supported` / `partially` / `unsupported` / `skipped`。
  final String verdict;

  /// 置信度（裁判不可用时为 null）。
  final double? confidence;

  /// 理由。
  final String reason;

  /// 是否通过（`partially` 也算通过：有依据但不够强）。
  bool get passed => verdict == 'supported' || verdict == 'partially';
}

/// 一次语义核验的汇总。
final class SemanticVerification {
  /// 创建汇总。
  const SemanticVerification({
    required this.available,
    this.checks = const [],
    this.unavailableReason = '',
  });

  /// 裁判是否可用（false → 全部 claim 记 `skipped`，不产出置信度）。
  final bool available;

  /// 逐条结果。
  final List<SemanticCheck> checks;

  /// 不可用原因（中文短句，用于界面明示）。
  final String unavailableReason;

  /// 通过数。
  int get passed => checks.where((c) => c.passed).length;

  /// 未通过数。
  int get failed => checks.where((c) => c.verdict == 'unsupported').length;

  /// 跳过数（裁判不可用）。
  int get skipped => checks.where((c) => c.verdict == 'skipped').length;
}

/// 对一组 claim 做语义核验。
///
/// 只核验带文本的主张（numeric 已由确定性重算覆盖，无需再问裁判）。
Future<SemanticVerification> verifySemantics({
  required Judge? judge,
  required List<Claim> claims,
  required Map<String, Evidence> evidenceById,
  int maxClaims = 20,
}) async {
  if (judge == null || !await judge.available) {
    return SemanticVerification(
      available: false,
      checks: [
        for (final claim in claims.take(maxClaims))
          SemanticCheck(claimId: claim.claimId, verdict: 'skipped'),
      ],
      unavailableReason: '裁判通道未配置或不可达，本次未做语义核验（不产出置信度）',
    );
  }

  final checks = <SemanticCheck>[];
  for (final claim in claims.take(maxClaims)) {
    // 数值主张由工具重算覆盖，语义核验对它没有增量。
    if (claim.claimType == ClaimType.numeric) {
      checks.add(SemanticCheck(claimId: claim.claimId, verdict: 'skipped'));
      continue;
    }
    final supporting = [
      for (final id in claim.evidenceIds)
        if (evidenceById[id] != null) evidenceById[id]!,
    ];
    if (supporting.isEmpty) {
      checks.add(SemanticCheck(claimId: claim.claimId, verdict: 'unsupported'));
      continue;
    }
    try {
      final answer = await judge.ask(
        state: {
          'claim': claim.text,
          'subject': claim.subject,
          'evidence': [
            for (final item in supporting.take(3))
              {
                'title': item.title,
                'summary': item.summary,
                'value': item.value,
                'unit': item.unit,
              },
          ],
        },
        question: const ChoiceQuestion(
          instructions: '判断下列证据是否支持该结论。',
          criteria: {
            'supported': '证据直接支持结论',
            'partially': '证据部分支持，结论有超出证据的部分',
            'unsupported': '证据不支持或与结论矛盾',
          },
        ),
      );
      checks.add(
        SemanticCheck(
          claimId: claim.claimId,
          verdict: answer.choice,
          confidence: answer.confidence,
        ),
      );
    } on Object {
      // 单条失败不拖垮整轮：记 skipped，不编造判定。
      checks.add(SemanticCheck(claimId: claim.claimId, verdict: 'skipped'));
    }
  }

  return SemanticVerification(available: true, checks: checks);
}
