import 'package:cbr_maw/app/theme/theme.dart';
import 'package:cbr_maw/app/ui.dart';
import 'package:cbr_maw/features/research/media_tone/limitations_card.dart';
import 'package:flutter_test/flutter_test.dart';

MediaToneLimitations _complete() => MediaToneLimitations(
  corpusCoverage: 0.82,
  corpusDocuments: 9798,
  sourceDistributionEntropy: 2.4,
  lexiconHitRate: 0.61,
  llmTrackStatus: LlmTrackStatus.unavailable,
  validityStart: DateTime.utc(2015, 1, 5),
  validityEnd: DateTime.utc(2025, 9, 30),
  causalityStatement: '相关非因果：基调与压力同期相关，不构成因果关系。',
  caveats: const <String>['语料以政策文本为主，金融媒体缺失'],
);

void main() {
  group('门卫 admitToneConclusion', () {
    test('没有 limitations → 拒绝', () {
      final admission = admitToneConclusion(null);
      expect(admission, ToneAdmission.missingLimitations);
      expect(admission.allowed, isFalse);
    });

    test('披露不完整 → 拒绝', () {
      final incomplete = MediaToneLimitations(
        corpusCoverage: null,
        corpusDocuments: 0,
        sourceDistributionEntropy: 0,
        lexiconHitRate: 0,
        llmTrackStatus: LlmTrackStatus.unavailable,
        validityStart: null,
        validityEnd: null,
        causalityStatement: '',
      );
      final admission = admitToneConclusion(incomplete);
      expect(admission, ToneAdmission.incompleteLimitations);
      expect(admission.allowed, isFalse);
      expect(incomplete.missingFields, isNotEmpty);
    });

    test('披露完整 → 放行', () {
      final admission = admitToneConclusion(_complete());
      expect(admission, ToneAdmission.admitted);
      expect(admission.allowed, isTrue);
    });

    test('toJson 携带全部字段（导出报告用）', () {
      final json = _complete().toJson();
      expect(json['corpus_documents'], 9798);
      expect(json['llm_track_status'], 'unavailable');
      expect(json['missing_fields'], isEmpty);
    });
  });

  group('MediaToneLimitationsCard', () {
    testWidgets('完整披露渲染关键字段与放行状态', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.light(),
          home: Scaffold(
            body: MediaToneLimitationsCard(limitations: _complete()),
          ),
        ),
      );
      expect(find.text('局限披露'), findsOneWidget);
      expect(find.textContaining('9798 篇'), findsOneWidget);
      expect(find.text('不可用'), findsOneWidget);
      expect(find.textContaining('相关非因果'), findsOneWidget);
      expect(find.text(ToneAdmission.admitted.label), findsOneWidget);
    });

    testWidgets('null 披露渲染拒绝态，不是空白', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(body: MediaToneLimitationsCard(limitations: null)),
        ),
      );
      expect(find.textContaining('缺少局限披露'), findsOneWidget);
    });
  });
}
