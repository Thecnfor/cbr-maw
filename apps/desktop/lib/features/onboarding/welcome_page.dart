import 'package:cbr_maw_contracts/contracts_dart.dart';

import '../../app/ui.dart';

import '../../app/app_scope.dart';
import '../../app/app_state.dart';
import '../../app/data_mode.dart';
import '../../app/key_verifier.dart';
import '../../app/preferences.dart';
import '../../app/routes.dart';
import '../../app/shell/app_shell.dart';
import '../../app/theme/theme.dart';
import '../../app/theme/tokens.dart';
import '../../app/widgets/states.dart';
import '../../app/widgets/synthetic.dart';

/// 首次上手（docs/22 屏 1 + 屏 2）：填密钥 → 选数据模式。
///
/// - 居中单列，最大宽 480dp，不出现侧栏；
/// - 密钥输入密码模式，永不回显明文；粘贴值一律 trim（docs/21 的 CRLF 陷阱）；
/// - 错误按 401 / 网络 / 代理 三态分列（错在哪 / 怎么改 / 影响什么）；
/// - 「稍后再说」进入只读模式：可浏览本地数据与来源台账，研判入口置灰。
final class WelcomePage extends StatefulWidget {
  /// 创建页面。
  const WelcomePage({this.prober, super.key});

  /// 密钥校验器（测试注入；缺省走真实 DeepSeek 端点）。
  final KeyProber? prober;

  @override
  State<WelcomePage> createState() => _WelcomePageState();
}

class _WelcomePageState extends State<WelcomePage> {
  int _step = 0;
  final _key = TextEditingController();
  KeyProbeResult? _result;
  bool _busy = false;

  @override
  void dispose() {
    _key.dispose();
    super.dispose();
  }

  Future<void> _verify(AppState state) async {
    final value = _key.text.trim();
    setState(() {
      _busy = true;
      _result = null;
    });
    final prober =
        widget.prober ??
        DeepSeekKeyProber(
          baseUrl: state.config.llmBaseUrl,
          model: state.config.llmModel,
        );
    final result = await prober.verify(value);
    if (!mounted) {
      return;
    }
    if (result.outcome == KeyProbeOutcome.ok) {
      await state.saveSecret(SecretSlot.deepseek, value);
      if (!mounted) {
        return;
      }
      _key.clear();
      setState(() {
        _busy = false;
        _step = 1;
      });
      return;
    }
    setState(() {
      _busy = false;
      _result = result;
    });
  }

  Future<void> _finish(UiPreferences prefs, DataMode mode) async {
    await prefs.setDataMode(mode);
    await prefs.exitReadOnly();
    await prefs.completeOnboarding();
    AppShellNavigator.go(
      mode == DataMode.myData ? Routes.inbox : Routes.overview,
    );
  }

  Future<void> _skipReadOnly(UiPreferences prefs) async {
    await prefs.enterReadOnly();
    await prefs.completeOnboarding();
    AppShellNavigator.go(Routes.overview);
  }

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    final prefs = AppStateScope.prefsOf(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(Tokens.space6),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 480),
              child: _step == 0 ? _keyStep(state, prefs) : _dataModeStep(prefs),
            ),
          ),
        ),
      ),
    );
  }

  Widget _keyStep(AppState state, UiPreferences prefs) {
    final result = _result;
    final colors = SemanticColors.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          'CBR-MAW',
          style: Theme.of(context).textTheme.headlineMedium
              ?.copyWith(fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: Tokens.space1),
        Text(
          '跨境金融风险多智能体协同预警研究工作台',
          style: TextStyle(
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: Tokens.space6),
        Text('填写主模型密钥', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: Tokens.space1),
        const Text('密钥仅保存在本机；界面只显示脱敏结果，永不回显明文。'),
        const SizedBox(height: Tokens.space3),
        TextField(
          controller: _key,
          obscureText: true,
          autocorrect: false,
          enableSuggestions: false,
          onSubmitted: (_) => _verify(state),
          decoration: InputDecoration(
            labelText: '主模型密钥（DeepSeek）',
            hintText: state.hasApiKey
                ? '已配置：${state.masked(SecretSlot.deepseek)}'
                : 'sk-…',
          ),
        ),
        if (state.hasApiKey) ...[
          const SizedBox(height: Tokens.space2),
          Text(
            '当前已保存：${state.masked(SecretSlot.deepseek)}',
            style: TextStyle(fontSize: 12, color: colors.idleInk),
          ),
        ],
        if (result != null) ...[
          const SizedBox(height: Tokens.space3),
          _ProbeFailure(result: result),
        ],
        const SizedBox(height: Tokens.space4),
        Row(
          children: [
            FilledButton(
              onPressed: _busy ? null : () => _verify(state),
              child: _busy
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('验证并继续'),
            ),
            const SizedBox(width: Tokens.space2),
            TextButton(
              onPressed: _busy ? null : () => setState(() => _step = 1),
              child: const Text('跳过验证，先选数据'),
            ),
          ],
        ),
        const SizedBox(height: Tokens.space3),
        TextButton(
          onPressed: _busy ? null : () => _skipReadOnly(prefs),
          child: const Text('稍后再说（只读模式）'),
        ),
        const SizedBox(height: Tokens.space1),
        Text(
          '只读模式下可浏览本地数据与来源台账；研判入口置灰并说明原因。',
          style: TextStyle(fontSize: 12, color: colors.idleInk),
        ),
      ],
    );
  }

  Widget _dataModeStep(UiPreferences prefs) {
    final selected = prefs.dataMode;
    final kernelReady = AppStateScope.of(context).kernelState.name == 'ready';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text('选择数据模式', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: Tokens.space1),
        const Text('三选一，之后可在设置中更改。'),
        const SizedBox(height: Tokens.space4),
        for (final mode in DataMode.values) ...[
          _ModeCard(
            mode: mode,
            selected: selected == mode,
            kernelReady: kernelReady,
            onTap: () => _finish(prefs, mode),
          ),
          const SizedBox(height: Tokens.space3),
        ],
        TextButton(
          onPressed: () => _skipReadOnly(prefs),
          child: const Text('稍后再说（只读模式）'),
        ),
      ],
    );
  }
}

/// 错误三段式（401 / 网络 / 代理各自不同）。
final class _ProbeFailure extends StatelessWidget {
  const _ProbeFailure({required this.result});

  final KeyProbeResult result;

  @override
  Widget build(BuildContext context) {
    final colors = SemanticColors.of(context);
    final (IconData icon, Color ink, Color tint) = switch (result.outcome) {
      KeyProbeOutcome.unauthorized => (
        Icons.key_off_outlined,
        colors.dangerInk,
        colors.dangerTint,
      ),
      KeyProbeOutcome.proxy => (
        Icons.lan_outlined,
        colors.warnInk,
        colors.warnTint,
      ),
      _ => (Icons.wifi_off, colors.warnInk, colors.warnTint),
    };
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(Tokens.space3),
      decoration: BoxDecoration(
        color: tint,
        borderRadius: BorderRadius.circular(Tokens.radiusControl),
        border: Border.all(color: ink.withValues(alpha: 0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 18, color: ink),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  result.what,
                  style: TextStyle(color: ink, fontWeight: FontWeight.w600),
                ),
              ),
            ],
          ),
          const SizedBox(height: Tokens.space1),
          Text('怎么改：${result.how}'),
          Text('影响：${result.impact}'),
        ],
      ),
    );
  }
}

final class _ModeCard extends StatelessWidget {
  const _ModeCard({
    required this.mode,
    required this.selected,
    required this.onTap,
    required this.kernelReady,
  });

  final DataMode mode;
  final bool selected;
  final VoidCallback onTap;
  final bool kernelReady;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final recommended = mode == DataMode.myData;
    return Card(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(Tokens.radiusCard),
        child: Padding(
          padding: const EdgeInsets.all(Tokens.space4),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(mode.label, style: theme.textTheme.titleSmall),
                  ),
                  if (mode.synthetic) const SyntheticBadge(),
                  if (recommended)
                    const StatusTag(
                      label: '推荐：真实数据，结论可对外',
                      tone: BannerTone.ok,
                    ),
                  if (selected) ...[
                    const SizedBox(width: Tokens.space2),
                    Icon(
                      Icons.check_circle,
                      size: 16,
                      color: theme.colorScheme.primary,
                    ),
                  ],
                ],
              ),
              const SizedBox(height: Tokens.space1),
              Text(mode.description),
              if (mode.synthetic) ...[
                const SizedBox(height: Tokens.space2),
                Text(
                  '选择后，所有页面、图表与导出物都会携带 SYNTHETIC 标记。',
                  style: TextStyle(
                    fontSize: 12,
                    color: SemanticColors.of(context).warnInk,
                  ),
                ),
              ],
              if (mode == DataMode.existingWorkspace) ...[
                const SizedBox(height: Tokens.space2),
                _WorkspaceSummary(kernelReady: kernelReady),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// 已有工作区的序列数与最后入库时间；读取失败显式说明，不显示占位数字。
///
/// 只在内核就绪后才取数（未就绪时先显示不可达原因），避免拿不到数据时编造。
final class _WorkspaceSummary extends StatefulWidget {
  const _WorkspaceSummary({required this.kernelReady});

  final bool kernelReady;

  @override
  State<_WorkspaceSummary> createState() => _WorkspaceSummaryState();
}

class _WorkspaceSummaryState extends State<_WorkspaceSummary> {
  Future<WorkspaceInfoResult>? _future;

  @override
  void didUpdateWidget(covariant _WorkspaceSummary oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.kernelReady && !oldWidget.kernelReady) {
      _future = AppStateScope.read(context).repository.workspaceInfo();
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.kernelReady) {
      return Text(
        '内核未就绪，工作区信息暂不可读；选择后仍可先浏览，读取失败会显式提示。',
        style: TextStyle(
          fontSize: 12,
          color: SemanticColors.of(context).warnInk,
        ),
      );
    }
    return FutureBuilder<WorkspaceInfoResult>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const SkeletonBlock(height: 14, width: 220);
        }
        final info = snapshot.data;
        if (info == null) {
          return Text(
            '工作区当前不可读。选择后仍可先浏览，读取失败会显式提示。',
            style: TextStyle(
              fontSize: 12,
              color: SemanticColors.of(context).warnInk,
            ),
          );
        }
        return Text(
          '${info.seriesCount} 条序列 · 最后入库 ${info.lastIngestAt ?? '尚无记录'}',
          style: const TextStyle(fontSize: 12),
        );
      },
    );
  }
}
