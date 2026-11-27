import 'package:cbr_maw_contracts/contracts_dart.dart';

import '../agents/investigation_controller.dart';
import '../agents/llm/llm_channel.dart';
import '../agents/memory/memory_store.dart';
import '../agents/roles/prompt_builder.dart';
import '../agents/roles/role_config.dart';
import '../agents/tools/tool_registry.dart';
import '../core/bundle_asset_source.dart';
import '../core/clock.dart';
import '../data/gate/tool_invoker.dart';
import '../agents/signals/kernel_knowledge_source.dart';
import '../agents/signals/kernel_reflection.dart';
import '../agents/signals/kernel_signal_source.dart';
import 'app_state.dart';

/// 研判控制器装配（外壳 → Agent 编排）。
///
/// 依赖方向：`app/` 只依赖 `agents/` 的**公开接口**（固定契约），
/// 不假设编排内部结构。模型不可用时**不注入任何 Mock**：
/// 控制器会产出 `RunFailed` 并引导用户到设置页。
final class AgentBootstrapFactory {
  const AgentBootstrapFactory._();

  /// 创建控制器。
  static Future<InvestigationController> create(AppState state) async {
    final assets = BundleAssetSource();
    final catalog = await RoleCatalog.load(assets);
    final prompts = await PromptBuilder.load(assets);
    final secrets = _AppSecretProvider(state);
    final registry = ToolRegistry(
      specs: catalog.specs,
      invoker: _GatedToolInvoker(state),
    );
    final settings = AgentSettings(
      catalog: catalog,
      prompts: prompts,
      registry: registry,
      generator: DeepSeekGenerator(
        secrets: secrets,
        baseUrl: state.config.llmBaseUrl,
        model: state.config.llmModel,
        timeout: Duration(seconds: state.config.llmTimeoutSeconds),
      ),
      judge: JevJudge(secrets: secrets),
      signalSource: KernelSignalSource(state.supervisor).read,
      reflectionSource: KernelReflection(state.supervisor).read,
      deepReflectionSource: KernelDeepReflection(state.supervisor).read,
      knowledgeSource: (query, asOf) => KernelKnowledgeSource(
        state.supervisor,
      ).read(query: query, asOf: asOf),
      memory: SidecarMemoryStore(state.supervisor),
    );
    return InvestigationController(
      runtime: AgentRuntime(settings),
      settings: settings,
    );
  }
}

/// 把 core 的密钥存储适配成 Agent 层的 [SecretProvider]。
final class _AppSecretProvider implements SecretProvider {
  _AppSecretProvider(this._state);

  final AppState _state;

  @override
  Future<String?> read(String key) async {
    // Agent 层用契约键名；映射到设置页的槽位。
    final slot = switch (key) {
      'DEEPSEEK_API_KEY' => SecretSlot.deepseek,
      'TYPESAFE_API_KEY' => SecretSlot.jev,
      _ => null,
    };
    if (slot == null) {
      return null;
    }
    return _state.secrets.read(slot.key);
  }
}

/// 把工具调用接到 Dart 门卫 → sidecar。
///
/// 越权时不发 RPC（由 [ToolInvoker] 保证），审计写入应用时间线。
final class _GatedToolInvoker implements ToolInvoker {
  _GatedToolInvoker(this._state);

  final AppState _state;

  @override
  Future<ToolInvocation> invoke({
    required String tool,
    required String asOf,
    required Map<String, Object?> params,
  }) async {
    final spec = ToolRegistry.specOf(tool);
    final role = _roleFor(spec);
    final outcome = await _state.invoker.invoke(
      role: role,
      tool: tool,
      params: params,
      asOf: asOf,
      idempotencyKey:
          '${tool}_${asOf}_${DateTime.now().microsecondsSinceEpoch}',
    );
    // 证据进会话索引：证据详情页要能显示工具版本与输入哈希。
    if (outcome is ToolCallSucceeded) {
      _state.recordToolEvidence(outcome.evidence);
    }
    return switch (outcome) {
      ToolCallSucceeded(:final evidence) => ToolInvocation(
        tool: evidence.tool,
        version: evidence.version,
        value: evidence.value,
        unit: evidence.unit,
        payload: evidence.params,
        title: evidence.title,
        summary: evidence.summary ?? '',
        data: evidence.data ?? const {},
        evidenceId: evidence.evidenceId,
        inputsHash: evidence.inputsHash,
        hash: evidence.hash,
      ),
      ToolCallDenied() => throw ToolUnavailable(tool, '角色越权，工具未执行'),
      ToolCallNeedsConfirmation() => throw ToolUnavailable(
        tool,
        '需要人工确认，工具未执行',
      ),
      ToolCallFailed(:final message) => throw ToolUnavailable(tool, message),
    };
  }

  /// 工具所属角色：取注册表允许的第一个角色（权限判定在门卫里按角色矩阵执行）。
  static String _roleFor(ToolSpec? spec) =>
      (spec == null || spec.allowedRoles.isEmpty)
      ? 'unknown'
      : spec.allowedRoles.first;
}

/// 供诊断页展示的契约时刻。
String debugAsOf() => Clock.asOfNow();
