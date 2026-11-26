import '../../app/ui.dart';

import '../../app/theme/tokens.dart';
import '../../app/widgets/common.dart';
import '../../app/widgets/states.dart';

/// 情景（docs/02 F5-4）：历史压力情景与情景推演。
///
/// 情景清单来自配置/本地库；当前没有可用情景时给出显式空态，不内置任何示例数值。
final class ScenariosPage extends StatelessWidget {
  /// 创建页面。
  const ScenariosPage({super.key});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const PageHeader(title: '情景', subtitle: '历史压力情景与冲击映射；情景假设与结论一一对应'),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(
              Tokens.space5,
              0,
              Tokens.space5,
              Tokens.space8,
            ),
            children: const [
              EmptyState(
                title: '尚无可用情景',
                message:
                    '情景需要由本地库中的真实历史区间定义。当前没有登记情景，'
                    '因此不显示任何推演结果。',
                icon: Icons.alt_route_outlined,
              ),
              SizedBox(height: Tokens.space4),
              InlineBanner(
                message:
                    '情景工具是确定性纯计算：输入冲击参数后由内核重算，'
                    '不调用模型，也不会生成示例行情。',
                tone: BannerTone.info,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// 时空（v2 预留占位页，docs/02 F6）：明确说明尚未实现，不伪造内容。
final class SpatialPage extends StatelessWidget {
  /// 创建页面。
  const SpatialPage({super.key});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const PageHeader(title: '时空', subtitle: 'v2 预留：夜光 / 遥感空间代理与时空内核'),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(
              Tokens.space5,
              0,
              Tokens.space5,
              Tokens.space8,
            ),
            children: const [
              EmptyState(
                title: '本页尚未实现',
                message:
                    '时空分析（六维压力状态、四视图类比、反例对照、条件分位预测）'
                    '计划在 v2 交付。当前不提供任何占位数据。',
                icon: Icons.public_outlined,
              ),
              SizedBox(height: Tokens.space4),
              InlineBanner(
                message: '夜光 / 遥感数据按需下载并本地预处理缓存，绝不内嵌样例。',
                tone: BannerTone.info,
              ),
            ],
          ),
        ),
      ],
    );
  }
}
