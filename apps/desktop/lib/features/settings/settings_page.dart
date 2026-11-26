import '../../app/ui.dart';

import '../../app/app_scope.dart';
import '../../app/app_state.dart';
import '../../app/routes.dart';
import '../../app/shell/app_shell.dart';
import '../../app/theme/theme.dart';
import '../../app/theme/tokens.dart';
import '../../app/widgets/common.dart';
import '../../app/widgets/states.dart';
import '../../core/errors.dart';

/// 设置（含首次运行向导 /settings/first-run）。
final class SettingsPage extends StatefulWidget {
  /// 创建页面。
  const SettingsPage({this.firstRun = false, super.key});

  /// 是否首次运行向导。
  final bool firstRun;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  int _step = 0;
  final _keyController = TextEditingController();
  final _jevController = TextEditingController();
  String? _error;
  bool _saving = false;

  @override
  void dispose() {
    _keyController.dispose();
    _jevController.dispose();
    super.dispose();
  }

  Future<void> _save(SecretSlot slot, String value) async {
    final state = AppStateScope.read(context);
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await state.saveSecret(slot, value);
    } on AppError catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) {
        setState(() => _saving = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    return widget.firstRun ? _buildWizard(state) : _buildSettings(state);
  }

  Widget _buildWizard(AppState state) {
    final steps = ['填写主模型密钥', '选择数据模式', '开始第一次研判'];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        PageHeader(
          title: '首次运行',
          subtitle: '三步完成配置；可随时跳过，之后在设置中重看',
          actions: [
            TextButton(
              onPressed: () => AppShellNavigator.go(Routes.overview),
              child: const Text('跳过'),
            ),
          ],
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: Tokens.space5),
          child: Row(
            children: [
              for (var i = 0; i < steps.length; i++) ...[
                Icon(
                  i < _step
                      ? Icons.check_circle
                      : i == _step
                      ? Icons.radio_button_checked
                      : Icons.radio_button_unchecked,
                  size: 18,
                  color: i <= _step
                      ? Theme.of(context).colorScheme.primary
                      : Theme.of(context).colorScheme.onSurfaceVariant,
                ),
                const SizedBox(width: 6),
                Text(steps[i]),
                if (i < steps.length - 1) const SizedBox(width: Tokens.space4),
              ],
            ],
          ),
        ),
        const SizedBox(height: Tokens.space4),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(
              Tokens.space5,
              0,
              Tokens.space5,
              Tokens.space8,
            ),
            children: [
              if (_error != null) ...[
                InlineBanner(message: _error!, tone: BannerTone.error),
                const SizedBox(height: Tokens.space3),
              ],
              if (_step == 0)
                SectionCard(
                  title: '第 1 步 · 填写主模型密钥',
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('主模型用于生成研判结论。密钥加密保存在本机，界面只显示脱敏结果。'),
                      const SizedBox(height: Tokens.space3),
                      TextField(
                        controller: _keyController,
                        obscureText: true,
                        decoration: InputDecoration(
                          labelText: '主模型密钥（DeepSeek）',
                          hintText: state.hasApiKey
                              ? '已配置：${state.masked(SecretSlot.deepseek)}'
                              : 'sk-…',
                        ),
                      ),
                      const SizedBox(height: Tokens.space2),
                      TextField(
                        controller: _jevController,
                        obscureText: true,
                        decoration: InputDecoration(
                          labelText: '裁判密钥（JEV，可选）',
                          hintText:
                              state.configuredSlots.contains(SecretSlot.jev)
                              ? '已配置：${state.masked(SecretSlot.jev)}'
                              : '未配置时将诚实降级为规则门卫',
                        ),
                      ),
                      const SizedBox(height: Tokens.space3),
                      Row(
                        children: [
                          FilledButton(
                            onPressed: _saving
                                ? null
                                : () async {
                                    await _save(
                                      SecretSlot.deepseek,
                                      _keyController.text,
                                    );
                                    await _save(
                                      SecretSlot.jev,
                                      _jevController.text,
                                    );
                                    if (mounted) {
                                      setState(() => _step = 1);
                                    }
                                  },
                            child: const Text('保存并继续'),
                          ),
                        ],
                      ),
                    ],
                  ),
                )
              else if (_step == 1)
                SectionCard(
                  title: '第 2 步 · 选择数据模式',
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        '默认使用 SYNTHETIC 仿真数据做离线回归，'
                        '任何界面都不会把它呈现为真实数据。真实数据需接入来源后抓取。',
                      ),
                      const SizedBox(height: Tokens.space3),
                      KeyValueRow(
                        label: '当前数据集',
                        value: state.config.syntheticDefault
                            ? 'SYNTHETIC 仿真'
                            : '真实抓取',
                      ),
                      KeyValueRow(label: '可写根', value: state.paths.dataHome),
                      KeyValueRow(label: '投递箱', value: state.paths.inboxDir),
                      const SizedBox(height: Tokens.space3),
                      Row(
                        children: [
                          OutlinedButton(
                            onPressed: () => setState(() => _step = 0),
                            child: const Text('上一步'),
                          ),
                          const SizedBox(width: Tokens.space2),
                          FilledButton(
                            onPressed: () => setState(() => _step = 2),
                            child: const Text('继续'),
                          ),
                        ],
                      ),
                    ],
                  ),
                )
              else
                SectionCard(
                  title: '第 3 步 · 开始第一次研判',
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('可以输入一个问题开始研判，或先到概览查看系统就绪度。'),
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
                            onPressed: () =>
                                AppShellNavigator.go(Routes.overview),
                            child: const Text('稍后再说'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildSettings(AppState state) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        PageHeader(
          title: '设置',
          subtitle: '密钥、路径、主题与数据模式',
          actions: [
            TextButton(
              onPressed: () => AppShellNavigator.go(Routes.settingsFirstRun),
              child: const Text('重看首次运行引导'),
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
              if (!state.secrets.osEncrypted) ...[
                const InlineBanner(
                  message:
                      '密钥当前使用受限权限文件保存（未使用系统密钥环）。'
                      '界面永不回显明文，但同机同用户的其他进程在获得文件权限后可能读取。',
                  tone: BannerTone.warn,
                  icon: Icons.key_outlined,
                ),
                const SizedBox(height: Tokens.space3),
              ],
              SectionCard(
                title: '密钥',
                child: Column(
                  children: [
                    for (final slot in SecretSlot.values)
                      _SecretRow(
                        slot: slot,
                        masked: state.configuredSlots.contains(slot)
                            ? state.masked(slot)
                            : null,
                        onSave: (value) => _save(slot, value),
                      ),
                    if (_error != null) ...[
                      const SizedBox(height: Tokens.space2),
                      InlineBanner(message: _error!, tone: BannerTone.error),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: Tokens.space4),
              SectionCard(
                title: '路径',
                child: Column(
                  children: [
                    KeyValueRow(label: '可写根', value: state.paths.dataHome),
                    KeyValueRow(
                      label: '只读资源根',
                      value: state.paths.resourceHome,
                    ),
                    KeyValueRow(label: '投递箱', value: state.paths.inboxDir),
                    KeyValueRow(label: '工作区', value: state.paths.workspacePath),
                  ],
                ),
              ),
              const SizedBox(height: Tokens.space4),
              SectionCard(
                title: '数据模式',
                child: Column(
                  children: [
                    KeyValueRow(
                      label: '默认数据集',
                      value: state.config.syntheticDefault
                          ? 'SYNTHETIC 仿真（仅测试与离线回归）'
                          : '真实抓取',
                    ),
                    KeyValueRow(label: '时区', value: state.config.timezone),
                    KeyValueRow(
                      label: '日频陈旧阈值',
                      value: '${state.config.staleThresholdDays} 天',
                    ),
                    KeyValueRow(
                      label: '月频陈旧阈值',
                      value: '${state.config.monthlyStaleThresholdDays} 天',
                    ),
                  ],
                ),
              ),
              const SizedBox(height: Tokens.space4),
              const SectionCard(
                title: '隐私与数据边界',
                child: Text(
                  '凭证仅保存在本机；发往模型的字段限于当前问题、角色提示词与已绑定的证据片段。'
                  '原始数据与本地库不离开本机。',
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

final class _SecretRow extends StatefulWidget {
  const _SecretRow({
    required this.slot,
    required this.masked,
    required this.onSave,
  });

  final SecretSlot slot;
  final String? masked;
  final Future<void> Function(String value) onSave;

  @override
  State<_SecretRow> createState() => _SecretRowState();
}

class _SecretRowState extends State<_SecretRow> {
  final _controller = TextEditingController();
  bool _editing = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: Tokens.space3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(widget.slot.label, style: theme.textTheme.bodyMedium),
                    Text(
                      widget.slot.purpose,
                      style: TextStyle(
                        fontSize: 12,
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              Text(
                widget.masked ?? '未配置',
                style: TextStyle(
                  fontFamily: 'monospace',
                  color: widget.masked == null
                      ? SemanticColors.of(context).warnInk
                      : theme.colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(width: Tokens.space2),
              TextButton(
                onPressed: () => setState(() => _editing = !_editing),
                child: Text(_editing ? '取消' : '修改'),
              ),
            ],
          ),
          if (_editing)
            Padding(
              padding: const EdgeInsets.only(top: Tokens.space2),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _controller,
                      obscureText: true,
                      decoration: const InputDecoration(hintText: '粘贴新密钥'),
                    ),
                  ),
                  const SizedBox(width: Tokens.space2),
                  FilledButton(
                    onPressed: () async {
                      await widget.onSave(_controller.text);
                      if (mounted) {
                        _controller.clear();
                        setState(() => _editing = false);
                      }
                    },
                    child: const Text('保存'),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
