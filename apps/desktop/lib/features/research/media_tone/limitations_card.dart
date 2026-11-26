/// 媒体基调（MediaTone）局限披露卡（docs/10 MT-12，P0）。
///
/// 两条产品约束：
/// 1. 每条 tone 类结论**必须**携带 [MediaToneLimitations]；没有就不许进最终判定
///    （门卫是纯函数 [admitToneConclusion]，可测、无 UI 依赖）。
/// 2. 披露字段只能来自**真实统计**；拿不到就写"未核验/不可达"，禁止填 0 或编数。
library;

import '../../../app/theme/tokens.dart';
import '../../../app/theme/theme.dart';
import '../../../app/ui.dart';
import '../../../app/widgets/common.dart';
import '../../../app/widgets/states.dart';

/// LLM 打分轨的核验状态（docs/21：DeepSeek 密钥 401 失效时必须显式标注）。
enum LlmTrackStatus {
  /// 已用真实模型跑通并抽样人工核验。
  verified('verified', '已核验'),

  /// 跑通但未做人工抽样核验。
  unverified('unverified', '未核验'),

  /// 模型不可用（密钥失效/不可达），只有词典轨。
  unavailable('unavailable', '不可用'),

  /// 该结论不依赖 LLM 轨。
  notUsed('not_used', '未使用');

  const LlmTrackStatus(this.wire, this.label);

  /// JSON 字面量。
  final String wire;

  /// 界面标签。
  final String label;
}

/// tone 类结论的局限披露。
final class MediaToneLimitations {
  /// 创建披露。
  const MediaToneLimitations({
    required this.corpusCoverage,
    required this.corpusDocuments,
    required this.sourceDistributionEntropy,
    required this.lexiconHitRate,
    required this.llmTrackStatus,
    required this.validityStart,
    required this.validityEnd,
    required this.causalityStatement,
    this.caveats = const <String>[],
  });

  /// 语料覆盖率（0–1）：目标区间内有文本的交易日占比；未知为 null。
  final double? corpusCoverage;

  /// 语料篇数（真实计数）。
  final int corpusDocuments;

  /// 来源分布熵（bits）：来源越集中越低；单一来源为 0。
  final double sourceDistributionEntropy;

  /// 词典命中率（0–1）：命中词条的文本占比。
  final double lexiconHitRate;

  /// LLM 轨核验状态。
  final LlmTrackStatus llmTrackStatus;

  /// 结论有效区间起点（含）。
  final DateTime? validityStart;

  /// 结论有效区间终点（含）。
  final DateTime? validityEnd;

  /// 「相关非因果」声明（必须非空）。
  final String causalityStatement;

  /// 额外已知局限（如实列出，如"语料以政策文本为主"）。
  final List<String> caveats;

  /// 缺字段的项（中文短句），空表示披露完整。
  List<String> get missingFields => <String>[
    if (corpusCoverage == null) '语料覆盖率缺失',
    if (sourceDistributionEntropy <= 0) '来源分布熵缺失（单一来源或未统计）',
    if (lexiconHitRate <= 0) '词典命中率缺失',
    if (validityStart == null || validityEnd == null) '结论有效区间缺失',
    if (causalityStatement.trim().isEmpty) '「相关非因果」声明缺失',
  ];

  /// 披露是否完整（缺任何一项都不算）。
  bool get isComplete => missingFields.isEmpty;

  /// 序列化（导出报告必须携带）。
  Map<String, Object?> toJson() => <String, Object?>{
    'corpus_coverage': corpusCoverage,
    'corpus_documents': corpusDocuments,
    'source_distribution_entropy': sourceDistributionEntropy,
    'lexicon_hit_rate': lexiconHitRate,
    'llm_track_status': llmTrackStatus.wire,
    'validity_start': validityStart?.toIso8601String(),
    'validity_end': validityEnd?.toIso8601String(),
    'causality_statement': causalityStatement,
    'caveats': caveats,
    'missing_fields': missingFields,
  };
}

/// 门卫结论。
enum ToneAdmission {
  /// 可进入最终判定。
  admitted('admitted', '可进入最终判定'),

  /// 缺披露卡。
  missingLimitations('missing_limitations', '缺局限披露，不得进入最终判定'),

  /// 披露不完整。
  incompleteLimitations('incomplete_limitations', '局限披露不完整，不得进入最终判定');

  const ToneAdmission(this.wire, this.label);

  /// JSON 字面量。
  final String wire;

  /// 界面文案。
  final String label;

  /// 是否放行。
  bool get allowed => this == ToneAdmission.admitted;
}

/// 门卫：**没有 limitations 的 tone 类结论不得进入最终判定**（docs/10 MT-12）。
///
/// 纯函数，无 UI 依赖；[limitations] 为 null 即拒绝。
ToneAdmission admitToneConclusion(MediaToneLimitations? limitations) {
  if (limitations == null) {
    return ToneAdmission.missingLimitations;
  }
  return limitations.isComplete
      ? ToneAdmission.admitted
      : ToneAdmission.incompleteLimitations;
}

/// 局限披露卡：语料覆盖、来源熵、词典命中率、LLM 轨状态、有效区间、非因果声明。
final class MediaToneLimitationsCard extends StatelessWidget {
  /// 创建卡。
  const MediaToneLimitationsCard({required this.limitations, super.key});

  /// 披露数据（null 时渲染拒绝态，而不是空白卡）。
  final MediaToneLimitations? limitations;

  @override
  Widget build(BuildContext context) {
    final data = limitations;
    if (data == null) {
      return const SectionCard(
        title: '局限披露',
        child: InlineBanner(
          tone: BannerTone.error,
          message: '该基调结论缺少局限披露，不得进入最终判定。',
        ),
      );
    }
    final admission = admitToneConclusion(data);
    return SectionCard(
      title: '局限披露',
      trailing: Text(
        admission.label,
        style: TextStyle(
          color: admission.allowed
              ? SemanticColors.of(context).okInk
              : SemanticColors.of(context).dangerInk,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          KeyValueRow(
            label: '语料覆盖',
            value: data.corpusCoverage == null
                ? '不可达'
                : '${(data.corpusCoverage! * 100).toStringAsFixed(1)}%'
                      '（${data.corpusDocuments} 篇）',
          ),
          KeyValueRow(
            label: '来源分布熵',
            value: data.sourceDistributionEntropy > 0
                ? '${data.sourceDistributionEntropy.toStringAsFixed(2)} bits'
                : '不可达',
          ),
          KeyValueRow(
            label: '词典命中率',
            value: data.lexiconHitRate > 0
                ? '${(data.lexiconHitRate * 100).toStringAsFixed(1)}%'
                : '不可达',
          ),
          KeyValueRow(label: 'LLM 轨', value: data.llmTrackStatus.label),
          KeyValueRow(
            label: '结论有效区间',
            value: data.validityStart == null || data.validityEnd == null
                ? '不可达'
                : '${_date(data.validityStart!)} → ${_date(data.validityEnd!)}',
          ),
          KeyValueRow(
            label: '非因果声明',
            value: data.causalityStatement.isEmpty
                ? '缺失'
                : data.causalityStatement,
          ),
          if (data.caveats.isNotEmpty) ...[
            const SizedBox(height: Tokens.space2),
            for (final caveat in data.caveats)
              Padding(
                padding: const EdgeInsets.only(top: Tokens.space1),
                child: Text('· $caveat'),
              ),
          ],
          if (!admission.allowed) ...[
            const SizedBox(height: Tokens.space3),
            InlineBanner(
              tone: BannerTone.warn,
              message: '披露不完整：${data.missingFields.join('；')}',
            ),
          ],
        ],
      ),
    );
  }

  static String _date(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-'
      '${d.day.toString().padLeft(2, '0')}';
}
