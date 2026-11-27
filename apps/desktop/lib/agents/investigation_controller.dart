/// R0–R5 编排与对外控制器（固定接口，见任务卡）。
///
/// 事件流是**冷流**：每次监听重新跑一遍研判。零 Mock 严格模式：模型不可用
/// → [RunFailed] 显式失败并引导设置页；预算耗尽 → 部分结论 + limitations。
library;

import 'dart:async';

import 'blackboard/evidence_blackboard.dart';
import 'signals/kernel_reflection.dart'
    show ReflectionEvidence, ReflectionPerformance;
import 'budget/budget.dart';
import 'claims/risk_level.dart';
import 'conflict/conflict_loss.dart';
import 'conflict/conflict_arbitrator.dart';
import 'conflict/conflict_detector.dart';
import 'llm/llm_channel.dart';
import 'models/domain.dart';
import 'roles/prompt_builder.dart';
import 'roles/role_agent.dart';
import 'roles/role_config.dart';
import 'run_events.dart';
import 'tools/tool_registry.dart';
import 'verification/semantic_verifier.dart';
import 'verification/verifier.dart';
import 'orchestrator/mode_flags.dart';

/// 研判设置（由应用外壳 / 配置注入）。
final class AgentSettings {
  /// 创建设置。
  const AgentSettings({
    required this.catalog,
    required this.prompts,
    required this.registry,
    this.generator,
    this.judge,
    this.defaultMode = CollaborationMode.collaborative,
    this.roles,
    this.signalSource,
    this.reflectionSource,
    this.deepReflectionSource,
    this.knowledgeSource,
    this.runHooks,
    this.ablation = const AblationFlags(),
  });

  /// 角色与编排配置。
  final RoleCatalog catalog;

  /// 提示词构建器。
  final PromptBuilder prompts;

  /// 工具注册表。
  final ToolRegistry registry;

  /// 生成器（null → 模型不可用，显式失败）。
  final TextGenerator? generator;

  /// 裁判（可选）。
  final Judge? judge;

  /// 默认模式。
  final CollaborationMode defaultMode;

  /// 参与角色（缺省 = 三主体）。
  final List<RoleId>? roles;

  /// 共享风险信号来源（生产由 kernel `signal.compute` 提供；测试/基准可注入）。
  ///
  /// 返回 null 表示该时点无可用信号——按零 Mock 规则如实记为「信号缺失」，
  /// **不得**用合成概率填充。
  final Future<RiskSignal?> Function(DateTime asOf)? signalSource;

  /// 浅层反思来源（`X-AlertAgent` 外环）；null = 不做跨时点归因。
  final Future<ReflectionEvidence?> Function(DateTime asOf)? reflectionSource;

  /// 知识库检索来源（`text` claim 的唯一合法依据）；null = 不检索。
  final Future<List<Evidence>> Function(String query, DateTime asOf)?
  knowledgeSource;

  /// 深层反思来源（预警效能复盘）；null = 不复盘。
  final Future<ReflectionPerformance?> Function(DateTime asOf)?
  deepReflectionSource;

  /// 每轮研判的生命周期钩子（基准 harness 用于落盘决策卡与审计）。
  final RunHooks? runHooks;

  /// 认知与证据消融开关（ADR-010 §1）。与协作模式正交。
  final AblationFlags ablation;
}

/// 每轮研判的生命周期钩子。
final class RunHooks {
  /// 创建钩子。
  const RunHooks({this.onDecision});

  /// 拿到最终决策卡（在 `RunFinished` 之前调用）。
  final void Function(DecisionCard decision)? onDecision;
}

/// Agent 运行时（编排器本体）。
final class AgentRuntime {
  /// 创建运行时。
  AgentRuntime(this.settings);

  /// 设置。
  final AgentSettings settings;

  /// 执行一次研判，产出事件流（冷流）。
  Stream<RunEvent> run({
    required String question,
    required String runId,
    required DateTime asOf,
    required CollaborationMode mode,
    RiskSignal? signal,
    MarketSnapshotData? snapshot,
    String? cancelToken,
    bool Function(String token)? isCancelled,
  }) async* {
    bool cancelled() => isCancelled?.call(cancelToken ?? '') ?? false;
    final flags = ModeFlags.of(mode);
    final specs = settings.catalog.specs;
    signal ??= await settings.signalSource?.call(asOf);
    // 跨时点反思：失败不阻断（反思是增强，不是结论前提）。
    // 消融开关关掉时**根本不调用**——这是消融实验能成立的前提：
    // 对照组不能只是「忽略结果」，必须是「没有发生」。
    final reflection = settings.ablation.llrReflection
        ? await settings.reflectionSource?.call(asOf)
        : null;
    final performance = settings.ablation.hlrReflection
        ? await settings.deepReflectionSource?.call(asOf)
        : null;
    final roles = settings.roles ?? settings.catalog.analyticalRoles;
    final guard = BudgetGuard(
      perRole: RoleBudget.fromSettings(settings.catalog.orchestration),
      maxWallClockMs: settings.catalog.orchestration.maxWallClockMs,
      maxJointCost: null,
      actorCount: roles.length,
      costModel: CostModel.fromSettings(settings.catalog.orchestration),
      startedAt: DateTime.now(),
    );
    final board = EvidenceBlackboard();
    final denied = settings.registry.denials;
    denied.clear();

    yield RunStarted(runId, mode.wire);

    // R0.1 确定性检索：共享信号 + 调用计划内的工具。
    final gathered = await _gather(
      runId: runId,
      asOf: asOf,
      signal: signal,
      roles: roles,
      registry: settings.registry,
      guard: guard,
    );
    // 知识库证据：没有它，`text` claim 会全部因「无 kb 证据」被丢弃。
    final knowledge = await settings.knowledgeSource?.call(question, asOf);
    if (knowledge != null && knowledge.isNotEmpty) {
      gathered.evidence.addAll(knowledge);
    }
    // 工具调用事件（含失败）；越权在角色层发生，见 R0.2。
    for (final call in gathered.calls) {
      yield ToolInvoked(runId, call.tool, call.params, call.result, false);
    }
    if (gathered.evidence.isEmpty) {
      yield RunFailed(
        runId,
        'E_NO_USABLE_EVIDENCE',
        '本地数据源当前不可用，未产出任何风险结论。请检查数据源状态或在设置页重试。',
        false,
        const ['全部来源失败；按零 Mock 规则不产出结论。'],
      );
      return;
    }
    board.addAll(gathered.evidence);
    if (cancelled()) {
      return;
    }

    // R0.2 角色并行分析（single 模式由一个通用 agent 依次完成三主体任务）。
    final outputs = <RoleId, AgentOutput>{};
    if (flags.useSingleAgent) {
      final single = await _runSingleAgent(
        runId: runId,
        asOf: asOf,
        question: question,
        roles: roles,
        evidence: gathered.evidence,
        signal: signal,
        guard: guard,
        reflection: reflection,
        performance: performance,
      );
      if (single == null) {
        yield RunFailed(
          runId,
          'E_LLM_UNAVAILABLE',
          '模型通道不可用（零 Mock 严格模式）。请到「设置 → 连接」配置并测试 DeepSeek 密钥后重试。',
          false,
          const ['未产出任何规则模板结论。'],
        );
        return;
      }
      outputs.addAll(single);
    } else {
      final agents = {
        for (final role in roles)
          role: RoleAgent(
            prompts: settings.prompts,
            registry: settings.registry,
            generator: settings.generator,
            judge: settings.judge,
          ),
      };
      for (final role in roles) {
        final agent = agents[role]!;
        yield AgentActivity(runId, role.wire, 'role_start', {'round': 0});
        final output = await agent.run(
          RoleRunInput(
            runId: runId,
            asOf: asOf,
            role: role,
            spec: specs[role]!,
            task: question,
            evidence: _visibleTo(specs[role]!, gathered.evidence),
            signal: signal,
            signalRef: signal?.evidenceId,
            reflection: reflection,
            performance: performance,
            weakEvidence:
                settings.ablation.evidenceStrength == EvidenceStrength.weak,
          ),
        );
        // 角色自己的生成 token 必须计费：否则 single / independent 臂的
        // 成本恒为 0，J = L + μC 在对照臂上完全失真。
        guard.chargeTokens(roles.indexOf(role), output.tokens.total);
        guard.chargeLatency(output.latencyMs);
        outputs[role] = output;
        // 墙钟熔断：预算耗尽必须停止继续委派，并标 partial（不得静默跑完）。
        if (guard.checkCircuitBreaker()) {
          yield AgentActivity(runId, 'coordinator', 'budget_tripped', {
            'reason': guard.tripReason ?? '墙钟超限',
            'roles_done': outputs.length,
          });
          break;
        }
        if (output.card != null) {
          for (final claim in output.card!.claims) {
            yield ClaimProduced(
              runId,
              claim.claimId,
              claim.text,
              claim.claimType.wire,
              claim.evidenceIds,
              claim.confidence?.toString(),
            );
          }
        }
        yield AgentActivity(runId, role.wire, 'role_done', {
          'status': output.status.wire,
          'toolCalls': output.toolCalls,
          'tokens': output.tokens.total,
          // LLM 自评是「模型怎么看」的唯一通道；不写进事件，终端与 UI 都看不到。
          if (output.llmAssessment != null)
            'assessment': output.llmAssessment!.wire,
          if (output.failure != null) 'error': output.failure!.message,
        });
      }
    }

    if (cancelled()) {
      return;
    }
    final degraded = [
      for (final entry in outputs.entries)
        if (entry.value.status != AgentStatus.ok) entry.key,
    ];
    final cards = [
      for (final role in roles)
        if (outputs[role]?.card != null) outputs[role]!.card!,
    ];
    if (cards.isEmpty) {
      final firstFailure = outputs.values
          .map((o) => o.failure)
          .whereType<AgentFailure>()
          .firstOrNull;
      yield RunFailed(
        runId,
        'E_ALL_ROLES_FAILED',
        firstFailure?.message ?? '全部角色分析失败，未产出结论（零 Mock 严格模式）。',
        false,
        const ['未用规则模板替代模型结论。'],
      );
      return;
    }

    // R1 证据共享。
    var evidenceShared = 0;
    if (flags.shareEvidence) {
      for (final output in outputs.values) {
        for (final item in output.evidence) {
          board.add(item);
          evidenceShared++;
        }
      }
      yield AgentActivity(runId, 'coordinator', 'evidence_share', {
        'shared': evidenceShared,
        'duplicate': board.duplicateCount,
      });
    }

    // R2 交叉验证（双轨）。
    final peerRefuted = <String>{};
    if (flags.crossValidate) {
      final findings = await _crossValidate(
        runId: runId,
        asOf: asOf,
        roles: roles,
        cards: cards,
        board: board,
        specs: specs,
        guard: guard,
      );
      for (final entry in findings.entries) {
        yield AgentActivity(runId, entry.key.wire, 'peer_review', {
          'findings': entry.value.map((f) => f.toJson()).toList(),
        });
      }
      // R2 的裁定必须回流：被同侪 `refuted` 的证据所支撑的主张，降级为
      // conflicted 交给 R4 仲裁。此前 findings 只进事件流，从不影响结论——
      // 交叉验证等于白跑。
      for (final entry in findings.entries) {
        for (final finding in entry.value) {
          if (finding.verdict != 'refuted') {
            continue;
          }
          for (final card in cards) {
            for (final claim in card.claims) {
              if (claim.evidenceIds.contains(finding.evidenceId)) {
                peerRefuted.add(claim.claimId);
              }
            }
          }
        }
      }
    }

    // R3 分歧识别。
    final allClaims = {
      for (final card in cards) ...{for (final c in card.claims) c.claimId: c},
    };
    var conflicts = <Conflict>[];
    if (flags.coordinate) {
      conflicts = detectConflicts(
        claims: allClaims.values.toList(),
        specs: specs,
        absTol: settings.catalog.orchestration.numericToleranceAbs,
        relTol: settings.catalog.orchestration.numericToleranceRel,
      );
      for (final conflict in conflicts) {
        yield ConflictFound(runId, conflict.conflictId, conflict.type.wire, {
          'subject': conflict.subject,
          'severity': conflict.severity.wire,
          'claimIds': conflict.claimIds,
        }, false);
      }
    }

    // R4 协调仲裁。
    final statusUpdates = <String, ClaimStatus>{
      for (final claimId in peerRefuted) claimId: ClaimStatus.conflicted,
    };
    var escalated = <String>[];
    if (flags.coordinate && conflicts.isNotEmpty) {
      final arbitration = await arbitrateConflicts(
        conflicts: conflicts,
        claimsById: allClaims,
        board: board,
        specs: specs,
        recompute: (tool, conflict) async {
          final outcome = await settings.registry.recompute(
            tool: tool,
            asOf: _date(asOf),
          );
          return outcome.evidence;
        },
      );
      conflicts = arbitration.conflicts;
      escalated = arbitration.escalated;
      statusUpdates.addAll(arbitration.claimStatusUpdates);
      for (final conflict in conflicts) {
        yield ConflictFound(runId, conflict.conflictId, conflict.type.wire, {
          'subject': conflict.subject,
          'resolvedBy': conflict.resolvedBy?.wire,
          'resolution': conflict.resolution,
        }, escalated.contains(conflict.conflictId));
      }
    }

    // 回写 claim 状态。
    final updatedCards = [
      for (final card in cards)
        card.copyWith(
          claims: [
            for (final claim in card.claims)
              statusUpdates.containsKey(claim.claimId)
                  ? claim.copyWith(status: statusUpdates[claim.claimId])
                  : claim,
          ],
        ),
    ];

    if (cancelled()) {
      return;
    }
    // R5.3 语义核验（JEV）：只核验带文本的主张，数值已由工具重算覆盖。
    final semantic = await verifySemantics(
      judge: settings.judge,
      claims: [for (final card in updatedCards) ...card.claims],
      evidenceById: board.evidenceById,
    );

    // R5.1 六类核验（确定性四类）。
    final base = verify(
      VerificationContext(
        runId: runId,
        asOf: asOf,
        cards: updatedCards,
        evidenceIndex: board.evidenceById,
        deniedToolCalls: List.of(denied),
        // 六类核验的「冲突」「预算」两类此前从未被喂入，等于只做了四类。
        conflicts: conflicts,
        budgetTruncated: guard.truncated,
        budgetTripped: guard.tripped,
        roleSpecs: specs,
        absTol: settings.catalog.orchestration.numericToleranceAbs,
        relTol: settings.catalog.orchestration.numericToleranceRel,
      ),
    );
    // 语义核验结果并入同一份报告（R5 六类核验的第 5 类）。
    // 裁判不可用时 available=false：passed 不因此判失败，但界面必须明示。
    final report = VerificationReport(
      runId: base.runId,
      numericChecksTotal: base.numericChecksTotal,
      numericChecksPassed: base.numericChecksPassed,
      citationChecksTotal: base.citationChecksTotal,
      citationChecksPassed: base.citationChecksPassed,
      semanticChecksTotal: semantic.checks.length,
      semanticChecksPassed: semantic.passed,
      semanticUnverified: semantic.skipped,
      unsupportedClaims: base.unsupportedClaims,
      permissionViolations: base.permissionViolations,
      leakageEvents: base.leakageEvents,
      schemaErrors: base.schemaErrors,
      issues: base.issues,
      passed: base.passed && (semantic.available ? semantic.failed == 0 : true),
    );

    // R5.2 合成。
    final finalLevel = RiskLevel.strongest(
      updatedCards.map((c) => c.riskLevel),
    );
    final partial = guard.truncated || guard.tripped || degraded.isNotEmpty;
    final limitations = systemLimitations(
      max: settings.catalog.orchestration.maxLimitations,
      signalMissing: signal == null,
      kbUnavailable: !board.items.any((e) => e.kind == EvidenceKind.kb),
      toolsFailed: gathered.failures.isNotEmpty,
      degradedRoles: degraded,
      budgetTruncated: guard.truncated || guard.tripped,
      partial: guard.truncated || guard.tripped,
      mode: mode.wire,
    );

    final finalAdvice = updatedCards
        .map((c) => c.recommendation)
        .where((r) => r.isNotEmpty)
        .join('\n');

    final decision = DecisionCard(
      runId: runId,
      asOf: asOf,
      mode: mode.wire,
      cards: updatedCards,
      evidence: board.items,
      conflicts: conflicts,
      verification: report,
      coordination: CoordinationStats(
        assessmentSpread: _assessmentSpread(outputs),
        toolCalls: guard.totalToolCalls,
        tokens: guard.totalTokens,
        latencyMs: guard.totalLatencyMs,
        evidenceShared: evidenceShared,
        duplicateEvidence: board.duplicateCount,
        conflictsDetected: conflicts.length,
        conflictsResolved: conflicts.where((c) => c.resolved).length,
        conflictsEscalated: escalated.length,
        jointCost: guard.jointCost,
        truncated: guard.truncated || guard.tripped,
      ),
      finalLevel: finalLevel,
      finalAdvice: finalAdvice,
      limitations: limitations,
      degradedRoles: degraded,
      createdAt: DateTime.now().toUtc(),
      partial: partial,
      numericMismatches: [
        for (final output in outputs.values) output.numericMismatches,
      ].fold(0, (a, b) => a + b),
      llmAssessments: {
        for (final entry in outputs.entries)
          if (entry.value.llmAssessment != null)
            entry.key: entry.value.llmAssessment!,
      },
      ablation: settings.ablation.toJson(),
      semanticChecks: [
        for (final check in semantic.checks)
          {
            'claim_id': check.claimId,
            'verdict': check.verdict,
            'confidence': check.confidence,
          },
      ],
      reflection: {
        if (reflection != null) ...{
          'similar_cases': reflection.cases.length,
          'history_size': reflection.historySize,
          'nearest_distance': reflection.cases.first.distance,
        },
        if (performance != null) ...{
          'evaluable_days': performance.evaluableDays,
          'precision': performance.precision,
          'recall': performance.recall,
          'lift': performance.lift,
        },
      },
      conflictLoss: conflictLossBreakdown(
        conflicts: conflicts,
        escalated: escalated,
      ),
    );

    settings.runHooks?.onDecision?.call(decision);

    yield AgentActivity(runId, 'coordinator', 'verification', {
      'passed': report.passed,
      'numericErrorRate': report.numericErrorRate,
      'leakageEvents': report.leakageEvents,
      'permissionViolations': report.permissionViolations,
    });

    yield RunFinished(
      runId,
      RunSummary(
        runId: runId,
        mode: mode.wire,
        riskLevel: finalLevel.wire,
        claimIds: [
          for (final card in updatedCards) ...card.claims.map((c) => c.claimId),
        ],
        evidenceIds: board.items.map((e) => e.evidenceId).toList(),
        conflictIds: conflicts.map((c) => c.conflictId).toList(),
        degradedRoles: degraded.map((r) => r.wire).toList(),
        limitations: decision.limitations,
        tokensUsed: guard.totalTokens,
        costUsd: guard.jointCost,
        partial: decision.partial,
        verification: {
          'passed': report.passed,
          'citation_ok': report.citationChecksPassed,
          'citation_total': report.citationChecksTotal,
          'numeric_error_rate': report.numericErrorRate,
          'semantic_checked': report.semanticChecksTotal,
          'semantic_unverified': report.semanticUnverified,
          'leakage_events': report.leakageEvents,
          'permission_violations': report.permissionViolations,
          'unsupported_claims': report.unsupportedClaims,
          'tool_calls': guard.totalToolCalls,
        },
        conflicts: [
          for (final conflict in conflicts.take(6))
            {
              'type': conflict.type.wire,
              'subject': conflict.subject,
              'roles': [for (final r in conflict.roles) r.wire],
              'resolved': conflict.resolved,
              'resolution': conflict.resolution,
            },
        ],
        roles: [
          for (final card in updatedCards)
            {
              'role': card.role.wire,
              'level': card.riskLevel.wire,
              'headline': card.headline,
              'evidence': card.evidenceIds.length,
              'degraded': degraded.contains(card.role),
              'action': card.action?.wire,
              'action_label': card.action?.label,
            },
        ],
      ),
    );
  }

  Future<_Gathered> _gather({
    required String runId,
    required DateTime asOf,
    required RiskSignal? signal,
    required List<RoleId> roles,
    required ToolRegistry registry,
    required BudgetGuard guard,
  }) async {
    final evidence = <Evidence>[];
    final failures = <String>[];
    final calls = <_ToolCall>[];

    // 共享信号作为 kind=signal 证据。
    if (signal != null) {
      final signalHash = sha256Hex(
        canonicalJson({
          'horizons': {
            for (final entry in signal.horizons.entries)
              '${entry.key}': entry.value,
          },
          'as_of': _date(asOf),
        }),
      );
      evidence.add(
        Evidence(
          evidenceId:
              signal.evidenceId ??
              'ev_sig_${_date(asOf)}_${signalHash.substring(0, 12)}',
          kind: EvidenceKind.signal,
          asOf: signal.asOf,
          title: '共享风险信号',
          summary: '模型 ${signal.modelVersion} 的压力概率',
          payload: {
            'horizons': {
              for (final entry in signal.horizons.entries)
                '${entry.key}': entry.value,
            },
            'percentile': signal.percentile,
            'model_version': signal.modelVersion,
          },
          value: signal.percentile,
          unit: 'ratio',
          source: const SourceRef(name: 'signal.compute'),
          producedBy: 'coordinator',
          createdAt: DateTime.now().toUtc(),
          hash: signalHash,
        ),
      );
    }

    // 每个角色的实际工具调用计划（docs/03 §1.2）。去重后按首个提出该工具
    // 的角色扣预算，避免同一口径重复计算。
    final plan = <String, RoleId>{};
    for (var i = 0; i < roles.length; i++) {
      for (final tool in _toolPlan[roles[i]] ?? const <String>[]) {
        plan.putIfAbsent(tool, () => roles[i]);
      }
    }
    // extraTools 是**排除**清单：消融臂 D（去掉新工具）靠它生效。
    // 此前只记录不生效，消融实验等于没做。
    if (settings.ablation.extraTools.isNotEmpty) {
      plan.removeWhere((tool, _) => settings.ablation.extraTools.contains(tool));
    }
    for (final entry in plan.entries) {
      final tool = entry.key;
      final slot = roles.indexOf(entry.value);
      if (!guard.requestToolCall(slot < 0 ? 0 : slot)) {
        failures.add('$tool: budget_exceeded');
        continue;
      }
      // 走带权限矩阵的 run（default_deny）：越权必须记入 denials 并跳过，
      // 否则 R5 的「越权」一类核验永远是 0，权限矩阵形同虚设。
      final outcome = await registry.run(
        role: entry.value,
        tool: tool,
        asOf: _date(asOf),
      );
      if (outcome.denied) {
        failures.add('$tool: permission_denied');
        calls.add(
          _ToolCall(tool, const {}, {
            'ok': false,
            'error': 'permission_denied',
            'role': entry.value.wire,
          }),
        );
        continue;
      }
      if (outcome.ok && outcome.evidence != null) {
        evidence.add(outcome.evidence!);
        calls.add(
          _ToolCall(tool, const {}, {
            'evidence_id': outcome.evidence!.evidenceId,
            'value': outcome.evidence!.value,
            'unit': outcome.evidence!.unit,
          }),
        );
      } else {
        failures.add('$tool: ${outcome.error ?? 'unknown'}');
        calls.add(
          _ToolCall(tool, const {}, {'ok': false, 'error': outcome.error}),
        );
      }
    }
    return _Gathered(evidence, failures, calls);
  }

  Future<Map<RoleId, AgentOutput>?> _runSingleAgent({
    required String runId,
    required DateTime asOf,
    required String question,
    required List<RoleId> roles,
    required List<Evidence> evidence,
    required RiskSignal? signal,
    required BudgetGuard guard,
    ReflectionEvidence? reflection,
    ReflectionPerformance? performance,
  }) async {
    final generator = settings.generator;
    if (generator == null) {
      return null;
    }
    final specs = settings.catalog.specs;
    final outputs = <RoleId, AgentOutput>{};
    for (final role in roles) {
      final agent = RoleAgent(
        prompts: settings.prompts,
        registry: settings.registry,
        generator: generator,
        judge: settings.judge,
      );
      final output = await agent.run(
        RoleRunInput(
          runId: runId,
          asOf: asOf,
          role: role,
          spec: specs[role]!,
          task: '$question\n（单智能体基线：本次只承担 ${specs[role]!.displayName} 任务）',
          evidence: _visibleTo(specs[role]!, evidence),
          signal: signal,
          signalRef: signal?.evidenceId,
          reflection: reflection,
          performance: performance,
          weakEvidence:
              settings.ablation.evidenceStrength == EvidenceStrength.weak,
        ),
      );
      guard.chargeTokens(roles.indexOf(role), output.tokens.total);
      guard.chargeLatency(output.latencyMs);
      outputs[role] = output;
      if (guard.checkCircuitBreaker()) {
        break;
      }
    }
    return outputs;
  }

  Future<Map<RoleId, List<CrossValidationFinding>>> _crossValidate({
    required String runId,
    required DateTime asOf,
    required List<RoleId> roles,
    required List<RiskCard> cards,
    required EvidenceBlackboard board,
    required Map<RoleId, RoleSpec> specs,
    required BudgetGuard guard,
  }) async {
    final generator = settings.generator;
    if (generator == null) {
      return const {};
    }
    final results = <RoleId, List<CrossValidationFinding>>{};
    for (final role in roles) {
      final peers = [
        for (final card in cards)
          if (card.role != role)
            for (final claim in card.claims)
              for (final id in claim.evidenceIds)
                if (board.lookup(id) != null) board.lookup(id)!,
      ];
      if (peers.isEmpty) {
        continue;
      }
      final spec = specs[role]!;
      final system = settings.prompts.renderCrossValidation(spec);
      final user = buildEvidencePrompt(
        asOf: asOf,
        task: '复核 peer 的关键数值证据（最多 2 条）。',
        evidence: const [],
        peerFacts: peers.take(6).toList(),
      );
      try {
        final response = await generator.generateJson(
          system: system,
          user: user,
          purpose: 'cross_validation:${role.wire}',
        );
        guard.chargeTokens(null, response.usage.total);
        final peerIds = peers.map((p) => p.evidenceId).toSet();
        final findings = parseFindings(response.json['findings'])
            .where((f) => peerIds.contains(f.evidenceId))
            .take(2)
            .toList();
        results[role] = findings;
      } on LlmFailure {
        // 复核失败 → 该角色本轮记 uncertain，不伪造结论。
        results[role] = const [];
      }
    }
    return results;
  }

  /// 角色实际工具调用计划（docs/03 §1.2）。
  static const Map<RoleId, List<String>> _toolPlan = {
    RoleId.regulator: [
      'systemic_risk',
      'risk_measure',
      'capital_flow',
      'scenario',
      'forecast',
    ],
    RoleId.investor: [
      'risk_measure',
      'capital_flow',
      'systemic_risk',
      'scenario',
      'forecast',
    ],
    RoleId.financing: ['funding_cost', 'scenario', 'risk_measure', 'forecast'],
    RoleId.crossValidator: [],
  };
}

/// 三主体 LLM 自评的等级跨度（无自评时按 0 处理）。
int _assessmentSpread(Map<RoleId, AgentOutput> outputs) {
  final orders = [
    for (final output in outputs.values)
      if (output.llmAssessment != null) output.llmAssessment!.order,
  ];
  if (orders.length < 2) {
    return 0;
  }
  orders.sort();
  return orders.last - orders.first;
}

/// 过滤出角色信息域内的证据。
///
/// 知识库证据的 domain 是 `policy.fulltext`，而 investor / financing 的信息域
/// 不含它——若不按角色过滤，它们一旦引用 KB 证据就会被核验层判越权，
/// 整轮 `passed=false`。证据可见性与权限校验必须用同一套口径。
List<Evidence> _visibleTo(RoleSpec spec, List<Evidence> evidence) => [
  for (final item in evidence)
    if (item.payload['domain'] is! String ||
        spec.allowsDomain(item.payload['domain']! as String))
      item,
];

final class _Gathered {
  _Gathered(this.evidence, this.failures, this.calls);

  final List<Evidence> evidence;
  final List<String> failures;
  final List<_ToolCall> calls;
}

final class _ToolCall {
  const _ToolCall(this.tool, this.params, this.result);

  final String tool;
  final Map<String, Object?> params;
  final Object? result;
}

/// 市场快照（编排层入参；数据层负责填充）。
final class MarketSnapshotData {
  /// 创建快照。
  const MarketSnapshotData({required this.asOf, this.series = const {}});

  /// 时点。
  final DateTime asOf;

  /// series_id → 值。
  final Map<String, double> series;
}

String _date(DateTime value) => value.toIso8601String().substring(0, 10);

/// 对外控制器（应用外壳唯一依赖）。
final class InvestigationController {
  /// 创建控制器。
  InvestigationController({
    required AgentRuntime runtime,
    required AgentSettings settings,
  }) : // 私有字段刻意不暴露：外壳只依赖固定接口，不得假设内部结构。
       // ignore: prefer_initializing_formals
       _runtime = runtime,
       // ignore: prefer_initializing_formals
       _settings = settings;

  final AgentRuntime _runtime;
  final AgentSettings _settings;
  final Map<String, RunSummary> _summaries = {};
  final Set<String> _cancelled = {};

  /// 一次研判的事件流（冷流：每次监听重新执行）。
  Stream<RunEvent> run(String question, {String? runId}) {
    final id = runId ?? 'run_${DateTime.now().microsecondsSinceEpoch}';
    return _runtime
        .run(
          question: question,
          runId: id,
          asOf: _resolveAsOf(question),
          mode: _settings.defaultMode,
          signal: null,
          cancelToken: id,
          isCancelled: (token) => _cancelled.contains(token),
        )
        .map((event) {
          if (event is RunFinished) {
            _summaries[id] = event.summary;
          }
          return event;
        })
        .takeWhile((_) => !_cancelled.contains(id));
  }

  /// 取消一次研判。
  Future<void> cancel(String runId) async {
    _cancelled.add(runId);
  }

  /// 最近一次研判摘要。
  Future<RunSummary?> lastSummary(String runId) async => _summaries[runId];

  DateTime _resolveAsOf(String question) {
    final match = RegExp(r'\b(\d{4}-\d{2}-\d{2})\b').firstMatch(question);
    if (match != null) {
      return DateTime.parse(match.group(1)!);
    }
    return DateTime.now();
  }
}
