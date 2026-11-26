import '../../app/ui.dart';

import '../../app/app_scope.dart';
import '../../app/routes.dart';
import '../../app/shell/app_shell.dart';
import '../../app/theme/tokens.dart';
import '../../app/widgets/common.dart';
import '../../app/widgets/states.dart';

/// 新手引导（docs/02 F1-8）：三张卡片，可跳过可重看。
final class OnboardingPage extends StatelessWidget {
  /// 创建页面。
  const OnboardingPage({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        PageHeader(
          title: '新手引导',
          subtitle: '三个要点，五分钟上手',
          actions: [
            TextButton(
              onPressed: () => AppShellNavigator.go(Routes.overview),
              child: const Text('跳过'),
            ),
          ],
        ),
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
                title: '1 · 先配密钥，再谈结论',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      '一个安装包 + 一个 API 密钥即可使用。密钥加密保存在本机，界面只显示脱敏结果。'
                      '未配置密钥时仍可浏览历史结论与本地数据。',
                    ),
                    const SizedBox(height: Tokens.space2),
                    KeyValueRow(
                      label: '当前状态',
                      value: state.hasApiKey ? '已配置主模型密钥' : '尚未配置',
                    ),
                  ],
                ),
              ),
              const SizedBox(height: Tokens.space4),
              SectionCard(
                title: '2 · 结论必须能回指到证据',
                child: const Text(
                  '每条结论强制绑定证据：数值绑工具证据，文本绑知识库证据，方向判断绑信号证据。'
                  '无证据的结论会被丢弃，不会出现在界面上。',
                ),
              ),
              const SizedBox(height: Tokens.space4),
              SectionCard(
                title: '3 · 拖进来就能用',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      '把 Excel / CSV 拖到窗口任意位置即可加入投递箱，系统会自动清洗入库。'
                      '不支持的格式会明确列出，不会被静默忽略。',
                    ),
                    const SizedBox(height: Tokens.space3),
                    Row(
                      children: [
                        FilledButton(
                          onPressed: () =>
                              AppShellNavigator.go(Routes.investigation),
                          child: const Text('开始第一次研判'),
                        ),
                        const SizedBox(width: Tokens.space2),
                        OutlinedButton(
                          onPressed: () => AppShellNavigator.go(Routes.inbox),
                          child: const Text('查看投递箱'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: Tokens.space4),
              const InlineBanner(
                message: '默认数据是 SYNTHETIC 仿真，仅用于测试与离线回归，不构成真实市场结论。',
                tone: BannerTone.info,
              ),
            ],
          ),
        ),
      ],
    );
  }
}
