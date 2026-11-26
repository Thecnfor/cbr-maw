import 'package:cbr_maw/app/data_mode.dart';
import 'package:cbr_maw/app/key_verifier.dart';
import 'package:flutter_test/flutter_test.dart';

/// 屏 1 / 屏 2 的纯逻辑部分：数据模式语义与密钥错误三态分列。
void main() {
  group('数据模式', () {
    test('只有「先看示例」携带 SYNTHETIC', () {
      expect(DataMode.sample.synthetic, isTrue);
      expect(DataMode.myData.synthetic, isFalse);
      expect(DataMode.existingWorkspace.synthetic, isFalse);
    });

    test('字面量可往返，未知值返回 null（不猜）', () {
      for (final mode in DataMode.values) {
        expect(DataMode.parse(mode.wire), mode);
      }
      expect(DataMode.parse('nope'), isNull);
      expect(DataMode.parse(null), isNull);
    });
  });

  group('密钥错误三态分列', () {
    test('三段式字段齐全且互不相同', () {
      const results = [
        KeyProbeResult(
          KeyProbeOutcome.unauthorized,
          '密钥无效或已过期',
          '确认账号状态与余额，或换一把 key',
          '无法调用模型；其余功能仍可用',
        ),
        KeyProbeResult(
          KeyProbeOutcome.network,
          '无法连接模型服务',
          '检查网络或代理设置（设置 → 网络）',
          '仅影响模型调用',
        ),
        KeyProbeResult(
          KeyProbeOutcome.proxy,
          '代理拒绝或不可达',
          '检查设置 → 网络中的代理地址',
          '仅影响模型调用；本地数据仍可浏览',
        ),
      ];
      for (final r in results) {
        expect(r.what, isNotEmpty);
        expect(r.how, isNotEmpty);
        expect(r.impact, isNotEmpty);
      }
      expect(results.map((r) => r.what).toSet().length, 3);
    });

    test('空密钥直接判为无效，不发网络请求', () async {
      final prober = DeepSeekKeyProber(
        baseUrl: 'https://example.invalid',
        model: 'x',
      );
      final result = await prober.verify('   ');
      expect(result.outcome, KeyProbeOutcome.unauthorized);
      expect(result.what, '未填写密钥');
    });

    test('非法 base_url 归为网络态，不抛异常', () async {
      final prober = DeepSeekKeyProber(baseUrl: 'not-a-url', model: 'x');
      final result = await prober.verify('sk-abc');
      expect(result.outcome, KeyProbeOutcome.network);
      expect(result.what, contains('接口地址非法'));
    });
  });
}
