#!/usr/bin/env python3
"""合并分片基准产物（shard*.json → console.json）。

两条硬规则：
1. **不去重伪造**：同一 `as_of` 出现两次即报错（说明分片参数配错），不静默取其一；
2. **口径一致**：所有分片的 model / base_url / arms / sampling.seed 必须相同，
   否则拒绝合并——混了模型或种子的结果不能当一次实验。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('root', help='含 shard*.json 的目录')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    root = Path(args.root)
    shards = sorted(root.glob('shard*.json'))
    if not shards:
        print(f'未找到分片产物：{root}/shard*.json')
        return 2

    base: dict | None = None
    records: dict[str, dict] = {}
    dates: dict[str, dict] = {}
    for path in shards:
        data = json.loads(path.read_text(encoding='utf-8'))
        if base is None:
            base = {k: data.get(k) for k in ('model', 'base_url', 'arms')}
            base['seed'] = (data.get('sampling') or {}).get('seed')
        else:
            for key in ('model', 'base_url', 'arms'):
                if data.get(key) != base[key]:
                    print(f'✘ {path.name}: {key} 与其他分片不一致（{data.get(key)} vs {base[key]}）')
                    return 1
            if (data.get('sampling') or {}).get('seed') != base['seed']:
                print(f'✘ {path.name}: 抽样种子不一致')
                return 1

        for record in data.get('records', []):
            day = record['as_of']
            if day in records:
                print(f'✘ 时点重复：{day}（分片参数配置有误）')
                return 1
            records[day] = record
        for item in (data.get('sampling') or {}).get('dates', []):
            dates[item['as_of']] = item

    merged = {
        'generated_at': None,
        'model': base['model'],
        'base_url': base['base_url'],
        'arms': base['arms'],
        'sampling': {'seed': base['seed'], 'dates': [dates[k] for k in sorted(dates)]},
        'n_runs': len(records),
        'records': [records[k] for k in sorted(records)],
        'shards': [p.name for p in shards],
    }
    out = Path(args.out)
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    # 按**已跑记录**的 y20 统计，而不是抽样清单（抽样清单是计划，不是实际）
    done_pressure = sum(1 for r in records.values() if r.get('y20') == 1)
    done_calm = sum(1 for r in records.values() if r.get('y20') == 0)
    planned = len(dates)
    print(f'合并 {len(shards)} 个分片：已跑 {len(records)}/{planned} 个时点'
          f'（压力 {done_pressure} / 平静 {done_calm}；未跑 {planned - len(records)}）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
