import 'package:cbr_maw_a2ui_catalog/cbr_maw_a2ui_catalog.dart';
import 'package:cbr_maw_design_system/cbr_maw_design_system.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:genui/genui.dart' hide text, divider;
import 'package:material_ui/material_ui.dart';

/// 用真实 `CatalogItem.widgetBuilder` 渲染一个组件（同 genui 官方测试写法）。
Widget render(
  CatalogItem item,
  Map<String, Object?> data, {
  void Function(UiEvent event)? onEvent,
}) {
  return MaterialApp(
    theme: CbrTheme.light(),
    home: Scaffold(
      body: Builder(
        builder: (context) => item.widgetBuilder(
          CatalogItemContext(
            type: item.name,
            data: data,
            id: 'root',
            buildChild: (_, [_]) => const SizedBox(),
            dispatchEvent: onEvent ?? (UiEvent event) {},
            buildContext: context,
            dataContext: DataContext(InMemoryDataModel(), DataPath.root),
            getComponent: (String componentId) => null,
            getCatalogItem: (String type) => null,
            surfaceId: 'surface1',
            reportError: (e, s) {},
          ),
        ),
      ),
    ),
  );
}

void main() {
  group('catalog 组件渲染（VC-1 / VC-3）', () {
    testWidgets('RoleCard 渲染角色、窗口与风险徽章', (tester) async {
      await tester.pumpWidget(
        render(roleCard, <String, Object?>{
          'role': 'financing',
          'headline': '偿付能力连续三期走弱',
          'riskLevel': 'high',
          'horizonDays': 20,
          'evidenceIds': <String>['ev_1', 'ev_2'],
        }),
      );
      expect(find.text('融资方'), findsOneWidget);
      expect(find.text('判定窗口 20 天'), findsOneWidget);
      expect(find.text('偿付能力连续三期走弱'), findsOneWidget);
      expect(find.text('高'), findsOneWidget);
      expect(find.text('引用证据 2 条'), findsOneWidget);
    });

    testWidgets('DataCardList 在「需授权」时不显示任何占位数值', (tester) async {
      await tester.pumpWidget(
        render(dataCardList, <String, Object?>{
          'cards': <Map<String, Object?>>[
            <String, Object?>{
              'title': '风险指数',
              'status': 'needsAuth',
              'sourceName': 'Bloomberg',
            },
          ],
        }),
      );
      expect(find.text('需授权'), findsOneWidget);
      expect(find.text('Bloomberg 未授权'), findsOneWidget);
      // 不得出现 0 / -- / N/A / —。
      for (final placeholder in <String>['0', '--', 'N/A', '—']) {
        expect(find.text(placeholder), findsNothing, reason: placeholder);
      }
    });

    testWidgets('DataCardList 正常卡显示数值与变化符号', (tester) async {
      await tester.pumpWidget(
        render(dataCardList, <String, Object?>{
          'cards': <Map<String, Object?>>[
            <String, Object?>{
              'title': '风险指数',
              'value': '72.4',
              'unit': '分',
              'trend': '+1.2',
              'trendDirection': 1,
            },
          ],
        }),
      );
      expect(find.textContaining('72.4'), findsOneWidget);
      // 箭头是冗余通道，必须与符号同时出现。
      expect(find.text('▲ +1.2'), findsOneWidget);
    });

    testWidgets('loading 状态渲染骨架而非内容', (tester) async {
      await tester.pumpWidget(
        render(roleCard, <String, Object?>{
          'state': 'loading',
          'role': 'investor',
          'headline': '不应出现',
        }),
      );
      expect(find.text('不应出现'), findsNothing);
      expect(find.byType(CbrSkeleton), findsOneWidget);
    });

    testWidgets('error 状态给三段式与重试', (tester) async {
      await tester.pumpWidget(
        render(decisionSummary, <String, Object?>{
          'state': 'error',
          'errorMessage': '数据模型缺字段。',
          'conclusion': '不应出现',
          'riskLevel': 'low',
        }),
      );
      expect(find.text('不应出现'), findsNothing);
      expect(find.text('组件未能渲染'), findsOneWidget);
      expect(find.text('重试'), findsOneWidget);
    });

    testWidgets('disabled 状态仍渲染内容但不可交互且语义禁用', (tester) async {
      await tester.pumpWidget(
        render(tag, <String, Object?>{'state': 'disabled', 'text': '降级运行'}),
      );
      expect(find.text('降级运行'), findsOneWidget);
      expect(find.byType(IgnorePointer), findsWidgets);
    });

    testWidgets('AccessRequired 不出现数值占位', (tester) async {
      await tester.pumpWidget(
        render(accessRequired, <String, Object?>{
          'source': 'Bloomberg',
          'reason': '未配置终端凭证。',
          'actionLabel': '前往授权',
        }),
      );
      expect(find.text('前往授权'), findsOneWidget);
      expect(find.textContaining('Bloomberg'), findsOneWidget);
      expect(find.text('0'), findsNothing);
    });

    testWidgets('ConfirmCard 的按钮文案具体且带动作风险级', (tester) async {
      await tester.pumpWidget(
        render(confirmCard, <String, Object?>{
          'title': '重新抓取全部来源',
          'actionRisk': 'highRisk',
          'body': <String>['这会覆盖本地库中 12 个来源的现有数据。'],
          'confirmLabel': '确认重新抓取并记录审计',
          'action': <String, Object?>{
            'event': <String, Object?>{'name': 'confirm_refetch'},
          },
        }),
      );
      expect(find.text('高风险操作'), findsOneWidget);
      expect(find.text('确认重新抓取并记录审计'), findsOneWidget);
      // 不得出现「确定 / OK」。
      expect(find.text('确定'), findsNothing);
      expect(find.text('OK'), findsNothing);
    });

    testWidgets('ConfirmCard 点击确认会回传具名动作', (tester) async {
      final events = <UiEvent>[];
      await tester.pumpWidget(
        render(confirmCard, <String, Object?>{
          'title': '导出研判结果',
          'actionRisk': 'confirmRequired',
          'body': <String>['会把当前研判写入本地文件。'],
          'confirmLabel': '确认导出',
          'action': <String, Object?>{
            'event': <String, Object?>{'name': 'confirm_export'},
          },
        }, onEvent: events.add),
      );
      await tester.tap(find.text('确认导出'));
      await tester.pump();
      expect(events, hasLength(1));
      expect((events.single as UserActionEvent).name, 'confirm_export');
    });

    testWidgets('EvidenceList 空列表给空态而不是空白', (tester) async {
      await tester.pumpWidget(
        render(evidenceList, <String, Object?>{'items': <Object?>[]}),
      );
      expect(find.text('暂无证据'), findsOneWidget);
    });

    testWidgets('ChartCard 有数据表等价通道', (tester) async {
      await tester.pumpWidget(
        render(chartCard, <String, Object?>{
          'title': '风险指数',
          'series': <Map<String, Object?>>[
            <String, Object?>{
              'name': '主序列',
              'colorIndex': 1,
              'points': <Map<String, Object?>>[
                <String, Object?>{'x': 0, 'y': 1},
                <String, Object?>{'x': 1, 'y': 2},
              ],
            },
          ],
        }),
      );
      expect(find.byTooltip('切换到数据表'), findsOneWidget);
      await tester.tap(find.byTooltip('切换到数据表'));
      await tester.pumpAndSettle();
      expect(find.byType(DataTable), findsOneWidget);
      expect(find.text('主序列'), findsOneWidget);
    });

    testWidgets('Text 不接受字号类变体之外的值', (tester) async {
      await tester.pumpWidget(
        render(text, <String, Object?>{'text': '结论', 'variant': 'title'}),
      );
      expect(find.text('结论'), findsOneWidget);
      final Text widget = tester.widget<Text>(find.text('结论'));
      expect(widget.style?.fontSize, CbrType.title.fontSize);
    });
  });
}
