import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart' show ChangeNotifier;

import 'package:cbr_maw_contracts/contracts_dart.dart';

import '../core/app_config.dart';
import '../core/app_log.dart';
import '../core/clock.dart';
import '../core/errors.dart';
import '../core/paths.dart';
import '../core/secret_store.dart';
import '../data/gate/permission_gate.dart';
import '../data/gate/tool_invoker.dart';
import '../data/sidecar/sidecar_supervisor.dart';
import '../data/sidecar/stdio_transport.dart';
import '../data/workspace_repository.dart';
import 'inbox_log.dart';

/// 密钥槽位。
enum SecretSlot {
  /// 主模型（DeepSeek，OpenAI 兼容）。
  deepseek('deepseek', '主模型密钥', '用于生成研判结论与草稿'),

  /// JEV 裁判（TypeSafe System One）。
  jev('jev', '裁判密钥', '用于准入判断、语义核验与冲突分类');

  const SecretSlot(this.key, this.label, this.purpose);

  /// 存储键。
  final String key;

  /// 中文名。
  final String label;

  /// 用途说明。
  final String purpose;
}

/// 应用级状态：配置、密钥、内核、审计。
///
/// 用 [ChangeNotifier] 而非 Riverpod：本工程 `riverpod` 是纯 Dart 包，
/// 不含 Flutter 绑定（见交付报告「依赖缺口」）。
final class AppState extends ChangeNotifier {
  AppState._({
    required this.paths,
    required this.config,
    required this.secrets,
    required this.log,
    required this.supervisor,
    required this.collector,
    required this.repository,
    required this.gate,
  });

  /// 启动装配。
  static Future<AppState> bootstrap(List<String> args) async {
    final paths = AppPaths.resolve(args);
    final log = AppLog();
    AppConfig config;
    try {
      await paths.ensureWritableDirs();
      config = await AppConfig.load(
        resourceConfigDir: paths.resourceConfigDir,
        userConfigDir: paths.userConfigDir,
      );
    } on AppError catch (e) {
      log.error('配置加载失败', error: e);
      config = AppConfig.defaults;
    }
    final secrets = await openSecretStore(paths.secretsDir);
    final supervisor = SidecarSupervisor(
      transportFactory: () => StdioSidecarTransport(
        executable: _sidecarExecutable('kernel'),
        arguments: [
          '--workspace',
          paths.workspacePath,
          '--data-home',
          paths.dataHome,
          '--resource-home',
          paths.resourceHome,
          '--log-level',
          'info',
        ],
      ),
      clientVersion: '0.1.0',
      contractVersion: '1.0.0',
      workspace: paths.workspacePath,
      dataHome: paths.dataHome,
      resourceHome: paths.resourceHome,
    );
    // collector 是独立 sidecar：数据抓取与 Inbox 清洗只在它那里，
    // 此前桌面端从不拉起它 → 抓取链路完全不可用（审计 B1）。
    final collector = SidecarSupervisor(
      transportFactory: () => StdioSidecarTransport(
        executable: _sidecarExecutable('collector'),
        arguments: [
          '--workspace',
          paths.workspacePath,
          '--data-home',
          paths.dataHome,
          '--resource-home',
          paths.resourceHome,
          '--log-level',
          'info',
        ],
      ),
      clientVersion: '0.1.0',
      contractVersion: '1.0.0',
      workspace: paths.workspacePath,
      dataHome: paths.dataHome,
      resourceHome: paths.resourceHome,
    );
    final repository = WorkspaceRepository(
      supervisor: supervisor,
      log: log,
      collector: collector,
    );
    final state = AppState._(
      paths: paths,
      config: config,
      secrets: secrets,
      log: log,
      supervisor: supervisor,
      collector: collector,
      repository: repository,
      gate: PermissionGate(now: Clock.asOfNow),
    );
    state._invoker = GatedToolInvoker(
      client: supervisor,
      gate: state.gate,
      auditSink: state.recordAudit,
    );
    state.supervisor.states.listen(state._onKernelState);
    await state._loadSecrets();
    return state;
  }

  /// 路径。
  final AppPaths paths;

  /// 运行配置。
  final AppConfig config;

  /// 密钥存储。
  final SecretStore secrets;

  /// 开发日志。
  final AppLog log;

  /// 内核监督者。
  final SidecarSupervisor supervisor;

  /// 采集器 sidecar（数据抓取 / Inbox 清洗）。
  final SidecarSupervisor collector;

  /// 数据仓储。
  final WorkspaceRepository repository;

  /// 权限门卫。
  final PermissionGate gate;

  /// 投递日志（窗口拖拽与输入框附件区共用）。
  final InboxLog inboxLog = InboxLog();

  final _toolEvidence = <String, ToolEvidence>{};

  /// 本次会话产生的工具证据（按证据 ID 索引）。
  ///
  /// 内核不把工具证据落 `audit_events` 视图，证据详情页要能一路点回
  /// 工具版本与输入哈希，就靠这份会话内索引（未命中时显式说明）。
  Map<String, ToolEvidence> get toolEvidence => Map.unmodifiable(_toolEvidence);

  /// 记录工具证据。
  void recordToolEvidence(ToolEvidence evidence) {
    _toolEvidence[evidence.evidenceId] = evidence;
    notifyListeners();
  }

  /// 工具调用器（门卫 + RPC）。
  GatedToolInvoker get invoker => _invoker;
  late final GatedToolInvoker _invoker;

  final _audit = <AuditEvent>[];
  final _auditController = StreamController<AuditEvent>.broadcast();
  final _secrets = <SecretSlot, String>{};
  SidecarState _kernelState = SidecarState.idle;

  /// 审计事件（新→旧）。
  List<AuditEvent> get auditEvents => List.unmodifiable(_audit.reversed);

  /// 审计流（时间线实时消费）。
  Stream<AuditEvent> get auditStream => _auditController.stream;

  /// 内核状态。
  SidecarState get kernelState => _kernelState;

  /// 已配置的密钥槽位。
  Set<SecretSlot> get configuredSlots => _secrets.keys.toSet();

  /// 是否已完成首启（至少配了主模型密钥）。
  bool get hasApiKey => _secrets.containsKey(SecretSlot.deepseek);

  /// 脱敏后的密钥（界面只读这个）。
  String masked(SecretSlot slot) => maskSecret(_secrets[slot] ?? '');

  /// 记录审计事件（时间线 + 诊断）。
  void recordAudit(AuditEvent event) {
    _audit.add(event);
    if (_audit.length > 500) {
      _audit.removeAt(0);
    }
    _auditController.add(event);
    notifyListeners();
  }

  /// 保存密钥；空串等价于删除。
  Future<void> saveSecret(SecretSlot slot, String value) async {
    final trimmed = value.trim();
    if (trimmed.isEmpty) {
      await secrets.delete(slot.key);
      _secrets.remove(slot);
    } else {
      await secrets.write(slot.key, trimmed);
      _secrets[slot] = trimmed;
    }
    notifyListeners();
  }

  Future<void> _loadSecrets() async {
    for (final slot in SecretSlot.values) {
      final value = await secrets.read(slot.key);
      if (value != null && value.isNotEmpty) {
        _secrets[slot] = value;
      }
    }
  }

  void _onKernelState(SidecarState state) {
    _kernelState = state;
    notifyListeners();
  }

  /// 退出：先优雅关闭内核。
  Future<void> shutdown() async {
    await supervisor.shutdown();
    // collector 必须一并优雅退出，否则会留下孤儿进程。
    await collector.shutdown();
    await _auditController.close();
    dispose();
  }

  static String _sidecarExecutable(String name) {
    final ext = Platform.isWindows ? '.exe' : '';
    // 与可执行文件同目录（安装包布局）。
    final exeDir = File(Platform.resolvedExecutable).parent.path;
    return '$exeDir${Platform.pathSeparator}$name$ext';
  }
}
