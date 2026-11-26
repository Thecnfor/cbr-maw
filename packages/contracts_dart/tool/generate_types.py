#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""由 contracts/ 下的 JSON Schema 生成 packages/contracts_dart 的 Dart 类型层。

用法（在仓库根执行）：
    python3 packages/contracts_dart/tool/generate_types.py

真源：
    contracts/<domain>/<method>.request.schema.json
    contracts/<domain>/<method>.response.schema.json
    contracts/tools/tools.json

产出：
    packages/contracts_dart/lib/src/methods.dart   方法 params/result 类型
    packages/contracts_dart/lib/src/tools.dart      工具注册表常量

生成物不得手工改动：改动真源后重跑本脚本。
"""
import json
import os
import re
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CONTRACTS = os.path.join(REPO, "contracts")
OUT = os.path.join(REPO, "packages/contracts_dart/lib/src")

RESERVED = {
    "class", "const", "default", "enum", "extends", "final", "for", "if", "in",
    "is", "new", "null", "rethrow", "return", "super", "switch", "this", "throw",
    "true", "false", "var", "void", "while", "with", "operator", "import",
    "export", "library", "part", "static", "abstract", "async", "await", "yield",
}

# 枚举取值集合 → Dart 枚举名（命名约定，不是契约内容）。
ENUM_NAMES = {
    ("collector", "kernel"): "SidecarId",
    ("t1Public", "t2Credentialed", "t3Terminal", "t4NotAllowed"): "LedgerTier",
    ("known", "toVerify", "notApplicable"): "EndpointStatus",
    ("reachable", "need_auth", "need_login", "restricted", "unreachable"): "SourceState",
    ("ok", "partial", "failed", "skipped"): "CollectStatus",
    ("market_daily", "macro_monthly", "pit_observations", "data_cards", "documents",
     "signals", "cfsi_history", "series_catalog", "ingest_batches", "audit_events"): "DbView",
    ("low", "medium", "high", "critical"): "RiskLevel",
    ("risk_measure", "systemic_risk", "capital_flow", "funding_cost", "scenario",
     "forecast", "knowledge_search", "dimension_dispersion",
     "capital_linkage"): "ToolName",
    ("inputs_hash", "evidence_id", "evidence_hash"): "HashKind",
    ("price", "return"): "ToolValuesAre",
    ("pct", "bp"): "ToolSpreadUnit",
    ("linear", "historical", "both"): "ToolScenarioMethod",
    ("asc", "desc"): "SortOrder",
}


def camel(name):
    parts = re.split(r"[_\-.]", name)
    out = parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])
    if out[0].isdigit():
        out = "f" + out
    return out


def pascal(name):
    c = camel(name)
    return c[:1].upper() + c[1:]


def method_class(method):
    return "".join(pascal(part) for part in method.split("."))


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class Registry:
    """收集枚举与嵌套类型。"""

    def __init__(self):
        self.enums = {}
        self.nested = {}

    def enum_name(self, values):
        key = tuple(values)
        name = ENUM_NAMES.get(key)
        if name is None:
            raise ValueError(f"未登记的枚举取值集合：{values}（在 ENUM_NAMES 中补名）")
        members = []
        for wire in values:
            member = camel(wire)
            if member in RESERVED:
                member += "Value"
            members.append((member, wire))
        existing = self.enums.setdefault(name, members)
        if [w for _, w in existing] != list(values):
            raise ValueError(f"枚举 {name} 取值不一致")
        return name


def unwrap(node):
    """剥掉 oneOf [T, null] 包装，返回 (非 null 分支, 是否可空)。"""
    if "oneOf" in node:
        nullable = False
        inner = None
        for sub in node["oneOf"]:
            if sub.get("type") == "null":
                nullable = True
            else:
                inner = sub
        if inner is None:
            raise ValueError(f"oneOf 节点缺少非 null 分支：{node}")
        return inner, nullable
    t = node.get("type")
    if isinstance(t, list) and "null" in t:
        inner = dict(node)
        inner["type"] = next((x for x in t if x != "null"))
        return inner, True
    return node, False


def base_type(node):
    """JSON Schema 节点 → Dart 基础类型（不含可空与枚举）。"""
    node, _ = unwrap(node)
    if "$ref" in node:
        return node["$ref"].split("/")[-1]
    if "enum" in node:
        return None  # 枚举单独处理
    if not node:
        return "Object?"
    t = node.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), None)
    if t == "string":
        return "String"
    if t == "integer":
        return "int"
    if t == "number":
        return "double"
    if t == "boolean":
        return "bool"
    if t == "array":
        return "List<%s>" % base_type(node["items"])
    if t == "object":
        if "properties" in node:
            return None  # 具名嵌套类型
        return "Map<String, Object?>"
    raise ValueError(f"无法映射的 schema 节点：{node}")


ARRAY_READERS = {
    "String": "strings",
    "int": "integers",
    "double": "numbers",
    "bool": "booleans",
    "Map<String, Object?>": "objects",
    "Object?": "values",
    "List<Object?>": "lists",
}


def field_spec(name, node, required, reg):
    """返回 (dart 类型, 构造实参, 是否可空, 是否枚举, 描述)。"""
    desc = node.get("description", "")
    inner, _ = unwrap(node)
    nullable = not required
    if "enum" in inner:
        values = [v for v in inner["enum"] if v is not None]
        dart_type = reg.enum_name(values)
        expr = (
            "switch (r.strOpt('%s')) { null => null, final v => %s.parse(v) }" % (name, dart_type)
            if nullable
            else "%s.parse(r.str('%s'))" % (dart_type, name)
        )
        return dart_type, expr, nullable, True, desc
    if "$ref" in inner:
        ref = inner["$ref"].split("/")[-1]
        expr = (
            "switch (r.objOpt('%s')) { null => null, final v => %s.parse(v) }" % (name, ref)
            if nullable
            else "%s.parse(r.obj('%s'))" % (ref, name)
        )
        return ref, expr, nullable, False, desc
    if inner.get("type") == "array" and "$ref" in inner["items"]:
        ref = inner["items"]["$ref"].split("/")[-1]
        expr = (
            "r.listOfOpt('%s', (e) => %s.parse(e.raw))" % (name, ref)
            if nullable
            else "r.listOf('%s', (e) => %s.parse(e.raw))" % (name, ref)
        )
        return "List<%s>" % ref, expr, nullable, False, desc
    t = base_type(inner)
    if t.startswith("List<"):
        reader = ARRAY_READERS[t[5:-1]]
        expr = "r.%s%s('%s')" % (reader, "Opt" if nullable else "", name)
        return t, expr, nullable, False, desc
    reader = {
        "String": "str",
        "int": "integer",
        "double": "number",
        "bool": "boolean",
    }.get(t)
    if reader is None:
        expr = ("r.objOpt('%s')" % name) if nullable else ("r.obj('%s')" % name)
        return t, expr, nullable, False, desc
    expr = "r.%s%s('%s')" % (reader, "Opt" if nullable else "", name)
    return t, expr, nullable, False, desc


def gen_enum(name, members):
    lines = ["/// 契约枚举 %s（字面量与 JSON 一致）。" % name, "enum %s {" % name]
    for i, (member, wire) in enumerate(members):
        lines.append("  %s('%s')%s" % (member, wire, "," if i < len(members) - 1 else ";"))
    lines += [
        "",
        "  const %s(this.wire);" % name,
        "",
        "  /// JSON 字面量。",
        "  final String wire;",
        "",
        "  /// 从 JSON 字面量解析（解析即校验）。",
        "  static %s parse(String raw) {" % name,
        "    for (final value in values) {",
        "      if (value.wire == raw) {",
        "        return value;",
        "      }",
        "    }",
        "    throw ContractFormatException('非法枚举取值：$raw');",
        "  }",
        "}",
    ]
    return "\n".join(lines)


def gen_data_class(class_name, fields, reg, doc):
    ctor, decls, args, tojson = [], [], [], []
    for name, node, required in fields:
        dart_type, expr, nullable, is_enum, desc = field_spec(name, node, required, reg)
        prop = camel(name)
        t = "%s?" % dart_type if nullable else dart_type
        ctor.append("    this.%s," % prop if nullable else "    required this.%s," % prop)
        decls.append("  /// %s" % desc)
        decls.append("  final %s %s;" % (t, prop))
        args.append("      %s: %s," % (prop, expr))
        if is_enum:
            tojson.append("    '%s': %s," % (name, prop + (".wire" if nullable else ".wire")))
        else:
            tojson.append("    '%s': %s," % (name, prop))
    lines = ["/// %s" % doc]
    if ctor:
        lines.append("final class %s {" % class_name)
        lines.append("  const %s({" % class_name)
        lines.extend(ctor)
        lines.append("  });")
    else:
        lines.append("final class %s {" % class_name)
        lines.append("  const %s();" % class_name)
    lines.append("")
    lines.append("  /// 从 JSON 对象解析（解析即校验；不符合契约抛 ContractFormatException）。")
    lines.append("  factory %s.parse(Object? json) {" % class_name)
    if args:
        lines.append("    final r = JsonReader(json, 'object');")
    else:
        lines.append("    JsonReader(json, 'object').requireKeys(<String>{});")
    if args:
        lines.append("    return %s(" % class_name)
        lines.extend(args)
        lines.append("    );")
    else:
        lines.append("    return const %s();" % class_name)
    lines.append("  }")
    lines.append("")
    lines.extend(decls)
    lines.append("")
    lines.append("  /// 回写为 JSON 对象。")
    lines.append("  Map<String, Object?> toJson() => {")
    lines.extend(tojson)
    lines.append("  };")
    lines.append("}")
    return "\n".join(lines)


def gen_method_class(class_name, fields, reg, method, kind, base_class):
    ctor, decls, args, tojson = [], [], [], []
    for name, node, required in fields:
        dart_type, expr, nullable, is_enum, desc = field_spec(name, node, required, reg)
        prop = camel(name)
        t = "%s?" % dart_type if nullable else dart_type
        ctor.append("    this.%s," % prop if nullable else "    required this.%s," % prop)
        decls.append("  /// %s" % desc)
        decls.append("  final %s %s;" % (t, prop))
        args.append("      %s: %s," % (prop, expr))
        if is_enum:
            # 可选枚举要空安全：`order.wire` 在 null 时直接抛 NoSuchMethod。
            tojson.append("    '%s': %s%s," % (name, prop, "?.wire" if nullable else ".wire"))
        else:
            tojson.append("    '%s': %s," % (name, prop))
    lines = ["/// `%s` %s。" % (method, kind)]
    lines.append("final class %s extends %s {" % (class_name, base_class))
    if ctor:
        lines.append("  const %s({" % class_name)
        lines.extend(ctor)
        lines.append("  });")
    else:
        lines.append("  const %s();" % class_name)
    lines.append("")
    lines.append("  /// 从 JSON 对象解析（解析即校验）。")
    lines.append("  factory %s.parse(Object? json) {" % class_name)
    if args:
        lines.append("    final r = JsonReader(json, '%s');" % kind.lower())
    else:
        lines.append("    JsonReader(json, '%s').requireKeys(<String>{});" % kind.lower())
    if args:
        lines.append("    return %s(" % class_name)
        lines.extend(args)
        lines.append("    );")
    else:
        lines.append("    return const %s();" % class_name)
    lines.append("  }")
    lines.append("")
    lines.append("  @override")
    lines.append("  String get method => '%s';" % method)
    lines.append("")
    lines.extend(decls)
    lines.append("")
    lines.append("  @override")
    lines.append("  Map<String, Object?> toJson() => {")
    lines.extend(tojson)
    lines.append("  };")
    lines.append("}")
    return "\n".join(lines)


def dart_literal(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(dart_literal(v) for v in value) + "]"
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def gen_tools():
    doc = load(os.path.join(CONTRACTS, "tools/tools.json"))
    lines = [
        "// GENERATED-DO-NOT-EDIT: 与 contracts/tools/tools.json 同源；",
        "// test/contracts_test.dart 断言两者一致。",
        "",
        "part of 'rpc.dart';",
        "",
        "/// 工具风险等级（L0 只读 / L1 写本地 / L2 触发外部动作需 HITL）。",
        "enum ToolRiskLevel {",
        "  /// L0：只读、无副作用。",
        "  l0('L0'),",
        "  /// L1：写本地。",
        "  l1('L1'),",
        "  /// L2：触发外部动作，需 HITL。",
        "  l2('L2');",
        "",
        "  const ToolRiskLevel(this.wire);",
        "",
        "  /// JSON 字面量。",
        "  final String wire;",
        "",
        "  /// 从 JSON 字面量解析（解析即校验）。",
        "  static ToolRiskLevel parse(String raw) {",
        "    for (final value in values) {",
        "      if (value.wire == raw) {",
        "        return value;",
        "      }",
        "    }",
        "    throw ContractFormatException('非法风险等级：$raw');",
        "  }",
        "}",
        "",
        "/// 工具注册表条目（contracts/tools/tools.json）。",
        "final class ToolSpec {",
        "  const ToolSpec({",
        "    required this.tool,",
        "    required this.version,",
        "    required this.riskLevel,",
        "    required this.allowedRoles,",
        "    required this.paramsSchemaRef,",
        "    required this.returns,",
        "    required this.deterministic,",
        "    required this.legacyRef,",
        "    required this.description,",
        "    required this.defaultParams,",
        "  });",
        "",
        "  /// 工具名。",
        "  final String tool;",
        "",
        "  /// 工具版本。",
        "  final String version;",
        "",
        "  /// 动作风险等级。",
        "  final ToolRiskLevel riskLevel;",
        "",
        "  /// 允许调用该工具的角色（roles.yaml 的 tool_permissions）。",
        "  final List<String> allowedRoles;",
        "",
        "  /// 入参 schema 路径。",
        "  final String paramsSchemaRef;",
        "",
        "  /// 返回值结构说明（值类型名；该字段不适用时为 null）。",
        "  final Map<String, String?> returns;",
        "",
        "  /// 是否确定性（工具绝不调用 LLM）。",
        "  final bool deterministic;",
        "",
        "  /// 旧版 Python 实现参照。",
        "  final String legacyRef;",
        "",
        "  /// 工具说明。",
        "  final String description;",
        "",
        "  /// 默认参数（与 tools.yaml 一致）。",
        "  final Map<String, Object?> defaultParams;",
        "",
        "  /// 角色是否被允许调用该工具（default_deny）。",
        "  bool allowsRole(String role) => allowedRoles.contains(role);",
        "",
        "  /// 回写为 JSON 对象。",
        "  Map<String, Object?> toJson() => {",
        "    'tool': tool,",
        "    'version': version,",
        "    'risk_level': riskLevel.wire,",
        "    'allowed_roles': allowedRoles,",
        "    'params_schema_ref': paramsSchemaRef,",
        "    'returns': returns,",
        "    'deterministic': deterministic,",
        "    'legacy_ref': legacyRef,",
        "    'description': description,",
        "    'default_params': defaultParams,",
        "  };",
        "}",
        "",
        "/// 工具注册表（contracts/tools/tools.json 的 Dart 常量）。",
        "const List<ToolSpec> toolRegistry = [",
    ]
    for entry in doc["tools"]:
        roles = ", ".join("'%s'" % r for r in entry["allowed_roles"])
        rets = ", ".join(
            "'%s': %s" % (k, "'%s'" % v if v is not None else "null")
            for k, v in entry["returns"].items()
        )
        params = ", ".join(
            "'%s': %s" % (k, dart_literal(v)) for k, v in entry["default_params"].items()
        )
        lines += [
            "  ToolSpec(",
            "    tool: '%s'," % entry["tool"],
            "    version: '%s'," % entry["version"],
            "    riskLevel: ToolRiskLevel.%s," % entry["risk_level"].lower(),
            "    allowedRoles: [%s]," % roles,
            "    paramsSchemaRef: '%s'," % entry["params_schema_ref"],
            "    returns: {%s}," % rets,
            "    deterministic: %s," % ("true" if entry["deterministic"] else "false"),
            "    legacyRef: '%s'," % entry["legacy_ref"],
            "    description: '%s'," % entry["description"].replace("'", "\\'"),
            "    defaultParams: {%s}," % params,
            "  ),",
        ]
    lines.append("];")
    return "\n".join(lines)


def main():
    reg = Registry()
    methods = []
    seen = set()
    for domain in ("collector", "kernel"):
        base = os.path.join(CONTRACTS, domain)
        for name in sorted(os.listdir(base)):
            if not name.endswith(".request.schema.json"):
                continue
            method = name[: -len(".request.schema.json")]
            if method in seen:
                # 核心生命周期方法在 collector/ 与 kernel/ 各有一份，内容一致。
                continue
            seen.add(method)
            req = load(os.path.join(base, name))
            res = load(os.path.join(base, name.replace(".request.", ".response.")))
            methods.append((method, req, res))

    # 先收集嵌套类型与枚举。
    # 同名 $defs 合并（request / response 各写了一份，改一处会被静默忽略）。
    for method, req, res in methods:
        for defs in (req.get("$defs", {}), res.get("$defs", {})):
            for def_name, def_node in defs.items():
                existing = reg.nested.get(def_name)
                if existing is None:
                    reg.nested[def_name] = def_node
                    continue
                props = dict(existing.get("properties", {}))
                props.update(def_node.get("properties", {}))
                required = set(existing.get("required", []))
                required |= set(def_node.get("required", []))
                merged = dict(def_node)
                merged["properties"] = props
                merged["required"] = sorted(required)
                reg.nested[def_name] = merged

    blocks = []
    for def_name, def_node in reg.nested.items():
        props = def_node.get("properties", {})
        required = set(def_node.get("required", []))
        fields = [(k, v, k in required) for k, v in props.items()]
        blocks.append(gen_data_class(def_name, fields, reg, "%s —— 契约嵌套对象。" % def_name))

    for method, req, res in methods:
        cls = method_class(method)
        params_props = req["properties"]["params"]
        params_required = set(params_props.get("required", []))
        params_fields = [(k, v, k in params_required) for k, v in params_props.get("properties", {}).items()]
        blocks.append(gen_method_class(cls + "Params", params_fields, reg, method, "params", "RpcParams"))

        result_props = res["oneOf"][0]["properties"]["result"]
        result_required = set(result_props.get("required", []))
        result_fields = [(k, v, k in result_required) for k, v in result_props.get("properties", {}).items()]
        blocks.append(gen_method_class(cls + "Result", result_fields, reg, method, "result", "RpcResult"))

    header = [
        "// GENERATED-DO-NOT-EDIT: 由 contracts/ 下的 JSON Schema 同源生成。",
        "// 真源：contracts/<domain>/<method>.{request,response}.schema.json。",
        "// 重新生成：python3 packages/contracts_dart/tool/generate_types.py",
        "",
        "part of 'rpc.dart';",
        "",
    ]
    enums = [gen_enum(name, members) for name, members in reg.enums.items()]
    with open(os.path.join(OUT, "methods.dart"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(header) + "\n" + "\n\n".join(enums) + "\n\n" + "\n\n".join(blocks) + "\n")
    with open(os.path.join(OUT, "tools.dart"), "w", encoding="utf-8") as fh:
        fh.write(gen_tools() + "\n")
    print("methods: %d, enums: %d, nested: %d" % (len(methods), len(reg.enums), len(reg.nested)))


if __name__ == "__main__":
    sys.exit(main())
