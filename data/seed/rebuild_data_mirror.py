"""从仓库内导出的 NDJSON 重建真实数据镜像（供 bench 与旧路径引用）。

来源（仓库内，已入库）：
  data/seed/pit_real_obs.jsonl   60313 条观测（27 序列 × 2015-01-05 → 2026-10-28）
  data/seed/documents.jsonl      9798 篇真实政策/财经文本

输出：
  /mnt/shared/recently/commorcial/data/pit_real.duckdb   （series_obs / series_meta / documents）
  /mnt/shared/recently/commorcial/data/custom/daily_series.csv
  /mnt/shared/recently/commorcial/data/custom/monthly_series.csv
  /mnt/shared/recently/commorcial/data/custom/policy_news.csv
  /mnt/shared/recently/commorcial/data/custom/real_data_manifest.json

用法：/tmp/cbrvenv/bin/python data/seed/rebuild_data_mirror.py
"""
import csv, json, os, sys
from collections import defaultdict

SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)))
MIRROR = '/mnt/shared/recently/commorcial/data'


def read_jsonl(path):
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def main():
    try:
        import duckdb
    except ImportError:
        sys.exit('需要 duckdb：uv pip install --python <venv>/bin/python duckdb')

    os.makedirs(f'{MIRROR}/custom', exist_ok=True)

    # ---- 1) DuckDB ----
    db = f'{MIRROR}/pit_real.duckdb'
    if os.path.exists(db):
        os.remove(db)
    con = duckdb.connect(db)
    con.execute("""
        CREATE TABLE series_obs(
            series_id VARCHAR, obs_date DATE, value DOUBLE,
            release_time TIMESTAMP, source VARCHAR, unit VARCHAR);
        CREATE TABLE series_meta(
            series_id VARCHAR PRIMARY KEY, name VARCHAR, source VARCHAR, frequency VARCHAR,
            coverage_start DATE, coverage_end DATE, release_lag_days INTEGER,
            pit_grade VARCHAR, unit VARCHAR, notes VARCHAR);
        CREATE TABLE documents(
            doc_id VARCHAR, publish_time TIMESTAMP, source VARCHAR,
            title VARCHAR, body VARCHAR, url VARCHAR, hash VARCHAR);
    """)

    obs_rows, meta_rows = [], {}
    for r in read_jsonl(f'{SEED}/pit_real_obs.jsonl'):
        obs_rows.append((
            r['series_id'], r['obs_date'], r['value'], r['release_time'],
            r.get('source'), r.get('unit')))
        sid = r['series_id']
        if sid not in meta_rows:
            meta_rows[sid] = (
                sid, r.get('name'), r.get('source'), r.get('frequency'),
                r.get('coverage_start'), r.get('coverage_end'),
                r.get('release_lag_days'), r.get('pit_grade'), r.get('unit'), r.get('notes'))

    con.executemany('INSERT INTO series_obs VALUES (?, CAST(? AS DATE), ?, CAST(? AS TIMESTAMP), ?, ?)', obs_rows)
    con.executemany('INSERT INTO series_meta VALUES (?, ?, ?, ?, CAST(? AS DATE), CAST(? AS DATE), ?, ?, ?, ?)',
                    list(meta_rows.values()))

    doc_rows = []
    for r in read_jsonl(f'{SEED}/documents.jsonl'):
        doc_rows.append((r.get('doc_id'), r.get('publish_time'), r.get('source'),
                         r.get('title'), r.get('body'), r.get('url'), r.get('hash')))
    con.executemany('INSERT INTO documents VALUES (?, CAST(? AS TIMESTAMP), ?, ?, ?, ?, ?)', doc_rows)
    con.close()

    # ---- 2) CSV 宽面板（按 daily / monthly 拆） ----
    daily = defaultdict(dict)
    monthly = defaultdict(dict)
    for r in read_jsonl(f'{SEED}/pit_real_obs.jsonl'):
        bucket = daily if r.get('frequency') == 'daily' else monthly
        bucket[r['obs_date']][r['series_id']] = r['value']

    for bucket, fname, freq in ((daily, 'daily_series.csv', 'daily'), (monthly, 'monthly_series.csv', 'monthly')):
        if not bucket:
            continue
        series_ids = sorted({sid for row in bucket.values() for sid in row})
        path = f'{MIRROR}/custom/{fname}'
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f)
            w.writerow(['date', 'release_time'] + series_ids)
            for date in sorted(bucket):
                row = bucket[date]
                release = '18:00:00' if freq == 'daily' else '10:00:00'
                w.writerow([date, f'{date} {release}'] + [row.get(sid, '') for sid in series_ids])

    # ---- 3) policy_news.csv ----
    path = f'{MIRROR}/custom/policy_news.csv'
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['doc_id', 'publish_time', 'title', 'content', 'source', 'url'])
        for r in read_jsonl(f'{SEED}/documents.jsonl'):
            w.writerow([r.get('doc_id'), r.get('publish_time'), r.get('title'),
                        r.get('body'), r.get('source'), r.get('url')])

    manifest = {
        'generated_at': '2026-11-26',
        'source': 'rebuilt-from-repo-seed (user-provided 原始数据)',
        'note': '由 data/seed/*.jsonl 重建；序列与观测逐字来自真实 PIT 库导出。',
        'daily_series_count': len({sid for row in daily.values() for sid in row}),
        'monthly_series_count': len({sid for row in monthly.values() for sid in row}),
        'observations': len(obs_rows),
        'documents': len(doc_rows),
        'series': sorted(meta_rows),
    }
    with open(f'{MIRROR}/custom/real_data_manifest.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"rebuilt: obs={len(obs_rows)} docs={len(doc_rows)} series={len(meta_rows)} -> {MIRROR}")


if __name__ == '__main__':
    main()
