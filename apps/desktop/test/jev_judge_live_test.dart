// JEV 裁判通道**真实联网**验证（只在提供密钥时运行）。
//
// 运行：
//   CBR_TYPESAFE_KEY=<key> flutter test test/jev_judge_live_test.dart
//
// 不提供密钥 → 跳过（绝不伪造裁判输出）。
import 'dart:io';

import 'package:cbr_maw/agents/llm/llm_channel.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('JEV 裁判：真实请求返回 choice + confidence + probabilities', () async {
    final key = Platform.environment['CBR_TYPESAFE_KEY'] ?? '';
    if (key.isEmpty) {
      markTestSkipped('未提供 CBR_TYPESAFE_KEY，跳过真实联网验证');
      return;
    }
    final judge = JevJudge(secrets: _EnvSecrets(key));
    expect(await judge.available, isTrue);

    final answer = await judge.ask(
      state: '跨境金融风险研判：CFSI 压力分 82（高位），跨境资金维度恶化，信用维度缓解。',
      question: const ChoiceQuestion(
        instructions: '综合以上状态，应判定为高风险还是低风险？',
        criteria: {'高风险': '压力分 ≥70 或跨境维度显著恶化', '低风险': '压力分 <70 且无维度恶化'},
      ),
    );
    // ignore: avoid_print
    print(
      'JEV 裁判真实返回：choice=${answer.choice} confidence=${answer.confidence} probabilities=${answer.probabilities}',
    );
    expect(answer.choice, anyOf('高风险', '低风险'));
    expect(answer.probabilities, isNotEmpty);
  }, timeout: const Timeout(Duration(minutes: 2)));
}

final class _EnvSecrets implements SecretProvider {
  _EnvSecrets(this.value);
  final String value;
  @override
  Future<String?> read(String key) async => value;
}
