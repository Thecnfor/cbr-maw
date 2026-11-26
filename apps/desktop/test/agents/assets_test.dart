import 'dart:io';

import 'package:cbr_maw/agents/models/domain.dart';
import 'package:cbr_maw/agents/roles/prompt_builder.dart';
import 'package:cbr_maw/agents/roles/role_config.dart';
import 'package:cbr_maw_contracts/contracts_dart.dart' show toolRegistry;
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// 校验随包资源（roles.json + prompts/*.md）真实可加载且与契约一致。
///
/// 注意：从 workspace 根跑 `flutter test apps/desktop` 时，测试资源清单只覆盖
/// 根包的 assets，`rootBundle` 读不到子包声明的资源（Flutter 测试工具链限制）。
/// 因此这里用磁盘读同一个文件验证内容与解析；`rootBundle` 路径由应用运行时使用。
final class _DiskBundle extends AssetBundle {
  /// 从 workspace 根跑测试时 cwd 是根，从包内跑时是包目录；两处都试。
  String _path(String key) =>
      File(key).existsSync() ? key : 'apps/desktop/$key';

  @override
  Future<ByteData> load(String key) async =>
      ByteData.sublistView(await File(_path(key)).readAsBytes());

  @override
  Future<String> loadString(String key, {bool cache = true}) =>
      File(_path(key)).readAsString();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final bundle = _DiskBundle();

  test('roles.json 可加载，三角色齐全', () async {
    final catalog = await RoleCatalog.load(bundle);
    expect(catalog.analyticalRoles, hasLength(3));
    expect(catalog.spec(RoleId.regulator).displayName, '监管主体智能体');
    expect(catalog.spec(RoleId.investor).horizonDays, 5);
    expect(catalog.spec(RoleId.financing).horizonDays, 20);
    expect(catalog.orchestration.modes, contains('demo'));
  });

  test('随包 roles.json 的 tool_permissions 与契约一致', () async {
    final catalog = await RoleCatalog.load(bundle);
    for (final role in catalog.analyticalRoles) {
      final spec = catalog.spec(role);
      for (final tool in spec.toolPermissions) {
        final contract = toolRegistry.where((t) => t.tool == tool).firstOrNull;
        expect(contract, isNotNull, reason: '工具 $tool 未在契约注册表中');
        expect(
          contract!.allowsRole(role.wire),
          isTrue,
          reason: '契约未授权 ${role.wire} 调用 $tool',
        );
      }
    }
  });

  test('提示词资源可加载，占位符被 RoleSpec 渲染', () async {
    final catalog = await RoleCatalog.load(bundle);
    final prompts = await PromptBuilder.load(bundle);
    final rendered = prompts.renderRoleWithSpec(catalog.spec(RoleId.regulator));
    expect(rendered, contains('监管主体智能体'));
    expect(rendered, isNot(contains('{{objective}}')));
    expect(rendered, isNot(contains('{{thresholds}}')));
    // 通用规则被追加。
    expect(rendered, contains('通用输出规则'));
  });

  test('交叉验证 prompt 渲染后无残留占位符', () async {
    final catalog = await RoleCatalog.load(bundle);
    final prompts = await PromptBuilder.load(bundle);
    final rendered = prompts.renderCrossValidation(
      catalog.spec(RoleId.investor),
    );
    expect(rendered, contains('投资主体智能体'));
    expect(rendered, isNot(contains('{{')));
  });
}
