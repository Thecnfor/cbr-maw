# -*- coding: utf-8 -*-
"""校验 contracts/examples 与 contracts/<domain>/*.schema.json 一致。

用法（在仓库根执行）：
    python3 packages/contracts_dart/tool/validate_examples.py

依赖：jsonschema（draft 2020-12）。
"""
import json
import os
import sys

try:
    from jsonschema import Draft202012Validator
except ImportError:
    print("需要 jsonschema：pip install jsonschema")
    raise SystemExit(2)

ROOT = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")),
    "contracts",
)

errors = []


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def check(schema_path, instance, label):
    schema = load(schema_path)
    validator = Draft202012Validator(schema)
    for err in validator.iter_errors(instance):
        errors.append(f"{label}: {err.message} @ {list(err.absolute_path)}")


domains = ["collector", "kernel"]
for dom in domains:
    for name in sorted(os.listdir(os.path.join(ROOT, dom))):
        if not name.endswith(".request.schema.json"):
            continue
        method = name[: -len(".request.schema.json")]
        base = os.path.join(ROOT, "examples", method)
        if not os.path.isdir(base):
            errors.append(f"{method}: 缺少样例目录")
            continue
        req_schema = os.path.join(ROOT, dom, f"{method}.request.schema.json")
        res_schema = os.path.join(ROOT, dom, f"{method}.response.schema.json")
        files = sorted(os.listdir(base))
        ok_req = ok_res = ok_err = False
        for fname in files:
            path = os.path.join(base, fname)
            data = load(path)
            if "error" in fname:
                check(res_schema, data, f"{method}/{fname}")
                ok_err = True
            elif "request" in fname:
                check(req_schema, data, f"{method}/{fname}")
                ok_req = True
            elif "response" in fname:
                check(res_schema, data, f"{method}/{fname}")
                ok_res = True
        if not (ok_req and ok_res and ok_err):
            errors.append(f"{method}: 样例类别缺失 req={ok_req} res={ok_res} err={ok_err}")

# schema 自身必须是合法的 draft 2020-12
for dom in domains:
    for name in sorted(os.listdir(os.path.join(ROOT, dom))):
        if not name.endswith(".schema.json"):
            continue
        path = os.path.join(ROOT, dom, name)
        try:
            Draft202012Validator.check_schema(load(path))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}: schema 非法：{exc}")

for name in sorted(os.listdir(os.path.join(ROOT, "tools"))):
    if not name.endswith(".schema.json"):
        continue
    path = os.path.join(ROOT, "tools", name)
    try:
        Draft202012Validator.check_schema(load(path))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{path}: schema 非法：{exc}")

if errors:
    print(f"FAIL ({len(errors)}):")
    for e in errors[:40]:
        print(" -", e)
    sys.exit(1)
print("OK: 样例与 schema 全部一致")
