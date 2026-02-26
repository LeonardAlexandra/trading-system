#!/usr/bin/env python3
"""
C9 压力测试：稳态验证（baseline）+ 压测（stress）。
先跑 baseline（低并发/单请求），100% 成功率通过后再跑 stress；baseline 未通过则压测结果不具备解释意义。
用法（项目根）：
  export TV_WEBHOOK_SECRET=your_secret
  export DATABASE_URL=sqlite+aiosqlite:///./trading_system.db
  # 先启动服务：uvicorn src.app.main:app --host 127.0.0.1 --port 8000
  python scripts/c9_stress_test.py --base-url http://127.0.0.1:8000 --read-only 20 5
  python scripts/c9_stress_test.py --base-url http://127.0.0.1:8000 --webhook 10 3
  python scripts/c9_stress_test.py --base-url http://127.0.0.1:8000 --skip-baseline --read-only 10 5  # 仅压测
"""
import argparse
import asyncio
import json
import os
import sys
import time
import hmac
import hashlib
import base64
from pathlib import Path

# 项目根
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import aiohttp
except ImportError:
    import urllib.request
    aiohttp = None

# 默认压测参数（可环境变量覆盖）
DEFAULT_CONCURRENCY = 10
DEFAULT_DURATION_SEC = 10
DEFAULT_WEBHOOK_RPS_CAP = 5  # 避免压垮 DB
BASELINE_CONCURRENCY = 1
BASELINE_REQUESTS = 4  # 每条只读 URL 各 1 请求，验证稳态

SIGNATURE_HEADER = "X-TradingView-Signature"


def _sign_body(secret: str, body: bytes) -> str:
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")


def _webhook_payload(signal_id_suffix: int) -> bytes:
    payload = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "timestamp": "2026-02-08T12:00:00Z",
        "strategy_id": "C9_STRESS",
        "action": "BUY",
    }
    return json.dumps(payload).encode("utf-8")


async def _request_aiohttp(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    data: bytes = None,
    headers: dict = None,
) -> tuple[int, float]:
    t0 = time.perf_counter()
    try:
        async with session.request(method, url, data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            await resp.read()
            return resp.status, time.perf_counter() - t0
    except Exception as e:
        return -1, time.perf_counter() - t0  # -1 表示异常


def _request_stdlib_sync(method: str, url: str, *, data: bytes = None, headers: dict = None) -> tuple[int, float]:
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, data=data, method=method)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
            return getattr(resp, "status", 200), time.perf_counter() - t0
    except Exception:
        return -1, time.perf_counter() - t0


BASELINE_RETRIES = 2  # 每个 URL 最多尝试次数，应对冷启动/偶发连接失败


async def run_baseline_read_only(base_url: str, use_aiohttp: bool) -> list[tuple[int, float]]:
    """稳态验证：低并发、固定请求数，用于验证 100% 成功率后再解释压测结果。每个 URL 失败时重试至多 BASELINE_RETRIES 次。"""
    urls = [
        f"{base_url}/healthz",
        f"{base_url}/api/health/summary",
        f"{base_url}/api/dashboard/decisions?limit=10",
        f"{base_url}/api/dashboard/executions?limit=10",
    ]
    results = []
    if use_aiohttp:
        async with aiohttp.ClientSession() as session:
            for url in urls:
                status, lat = -1, 0.0
                for _ in range(BASELINE_RETRIES):
                    status, lat = await _request_aiohttp(session, "GET", url)
                    if 200 <= status < 300:
                        break
                results.append((status, lat))
    else:
        for url in urls:
            status, lat = -1, 0.0
            for _ in range(BASELINE_RETRIES):
                status, lat = await asyncio.to_thread(_request_stdlib_sync, "GET", url)
                if 200 <= status < 300:
                    break
            results.append((status, lat))
    return results


async def run_read_only(
    base_url: str,
    concurrency: int,
    total_requests: int,
    use_aiohttp: bool,
) -> list[tuple[int, float]]:
    """只读：/healthz, /api/health/summary, /api/dashboard/decisions?limit=10"""
    results = []
    urls = [
        f"{base_url}/healthz",
        f"{base_url}/api/health/summary",
        f"{base_url}/api/dashboard/decisions?limit=10",
        f"{base_url}/api/dashboard/executions?limit=10",
    ]
    sem = asyncio.Semaphore(concurrency)

    async def one_request(session, url):
        async with sem:
            if use_aiohttp:
                return await _request_aiohttp(session, "GET", url)
            status, lat = await asyncio.to_thread(_request_stdlib_sync, "GET", url)
            return status, lat

    async def worker(session):
        nonlocal results
        for _ in range(total_requests // concurrency + 1):
            if len(results) >= total_requests:
                break
            url = urls[len(results) % len(urls)]
            status, lat = await one_request(session, url)
            results.append((status, lat))

    if use_aiohttp:
        async with aiohttp.ClientSession() as session:
            await asyncio.gather(*[worker(session) for _ in range(concurrency)])
    else:
        async def run_one(idx):
            url = urls[idx % len(urls)]
            return await asyncio.to_thread(_request_stdlib_sync, "GET", url)
        tasks = [run_one(i) for i in range(total_requests)]
        for i in range(0, len(tasks), concurrency):
            batch = tasks[i : i + concurrency]
            results.extend(await asyncio.gather(*batch))
    return results[:total_requests]


async def run_webhook(
    base_url: str,
    secret: str,
    concurrency: int,
    total_requests: int,
    use_aiohttp: bool,
) -> list[tuple[int, float]]:
    """POST /webhook/tradingview 带验签"""
    results = []
    url = f"{base_url}/webhook/tradingview"
    sem = asyncio.Semaphore(concurrency)

    async def one_webhook(session, i):
        async with sem:
            body = _webhook_payload(i)
            sig = _sign_body(secret, body)
            headers = {SIGNATURE_HEADER: sig, "Content-Type": "application/json"}
            if use_aiohttp:
                return await _request_aiohttp(session, "POST", url, data=body, headers=headers)
            status, lat = await asyncio.to_thread(_request_stdlib_sync, "POST", url, data=body, headers=headers)
            return status, lat

    if use_aiohttp:
        async with aiohttp.ClientSession() as session:
            tasks = [one_webhook(session, i) for i in range(total_requests)]
            results = await asyncio.gather(*tasks)
    else:
        results = []
        for i in range(total_requests):
            body = _webhook_payload(i)
            sig = _sign_body(secret, body)
            headers = {SIGNATURE_HEADER: sig, "Content-Type": "application/json"}
            status, lat = await asyncio.to_thread(_request_stdlib_sync, "POST", url, data=body, headers=headers)
            results.append((status, lat))
    return list(results)


def percentile(sorted_latencies: list, p: float) -> float:
    if not sorted_latencies:
        return 0.0
    k = (len(sorted_latencies) - 1) * p / 100.0
    f = int(k)
    if f >= len(sorted_latencies) - 1:
        return sorted_latencies[-1]
    return sorted_latencies[f] + (k - f) * (sorted_latencies[f + 1] - sorted_latencies[f])


def report(name: str, results: list[tuple[int, float]], duration_sec: float) -> dict:
    total = len(results)
    ok = sum(1 for s, _ in results if 200 <= s < 300)
    err = total - ok
    lats = sorted([lat for _, lat in results])
    return {
        "name": name,
        "total_requests": total,
        "success_count": ok,
        "error_count": err,
        "success_rate_pct": round(100.0 * ok / total, 2) if total else 0,
        "error_rate_pct": round(100.0 * err / total, 2) if total else 0,
        "duration_sec": round(duration_sec, 2),
        "rps": round(total / duration_sec, 2) if duration_sec > 0 else 0,
        "latency_p50_ms": round(percentile(lats, 50) * 1000, 2) if lats else 0,
        "latency_p95_ms": round(percentile(lats, 95) * 1000, 2) if lats else 0,
        "latency_p99_ms": round(percentile(lats, 99) * 1000, 2) if lats else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="C9 压力测试（稳态 baseline + stress）")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="服务 base URL")
    parser.add_argument("--skip-baseline", action="store_true", help="跳过 baseline，仅跑压测（仅当已确认系统稳态时使用）")
    parser.add_argument("--read-only", nargs=2, metavar=("CONCURRENCY", "DURATION_SEC"), help="仅只读接口压测")
    parser.add_argument("--webhook", nargs=2, metavar=("CONCURRENCY", "DURATION_SEC"), help="仅 webhook 压测（需 TV_WEBHOOK_SECRET）")
    parser.add_argument("--mixed", nargs=2, metavar=("CONCURRENCY", "DURATION_SEC"), help="只读+webhook 混合")
    parser.add_argument("--output", default=None, help="将汇总 JSON 写入文件")
    args = parser.parse_args()

    use_aiohttp = aiohttp is not None
    base_url = args.base_url.rstrip("/")
    secret = os.environ.get("TV_WEBHOOK_SECRET", "").strip()

    if args.webhook and not secret:
        print("TV_WEBHOOK_SECRET 未设置，无法运行 webhook 压测", file=sys.stderr)
        sys.exit(1)

    all_reports = []
    baseline_report = None
    start = time.perf_counter()

    run_stress = bool(args.read_only or args.webhook or args.mixed)
    if run_stress and not args.skip_baseline:
        print("[C9] Baseline (steady-state) run: concurrency=1, requests=4")
        baseline_results = asyncio.run(run_baseline_read_only(base_url, use_aiohttp))
        baseline_elapsed = time.perf_counter() - start
        baseline_report = report("baseline", baseline_results, baseline_elapsed)
        all_reports.append(baseline_report)
        print(json.dumps(baseline_report, indent=2, ensure_ascii=False))
        if baseline_report["success_rate_pct"] != 100:
            print("[C9] BASELINE FAIL: success_rate_pct != 100%, stress run skipped. Fix environment first.")
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump({"baseline_run": baseline_report, "stress_run": None, "baseline_pass": False, "environment": {"base_url": base_url}}, f, indent=2, ensure_ascii=False)
            sys.exit(1)
        print("[C9] BASELINE PASS: 100% success, proceeding to stress run.")

    if args.read_only:
        concurrency = int(args.read_only[0])
        duration_sec = float(args.read_only[1])
        total = max(concurrency * 2, int(duration_sec * 10))
        print(f"[C9] Read-only: concurrency={concurrency}, duration_sec={duration_sec}, total_requests≈{total}")
        results = asyncio.run(run_read_only(base_url, concurrency, total, use_aiohttp))
        elapsed = time.perf_counter() - start
        r = report("read_only", results, elapsed)
        all_reports.append(r)
        print(json.dumps(r, indent=2, ensure_ascii=False))

    if args.webhook:
        concurrency = min(int(args.webhook[0]), DEFAULT_WEBHOOK_RPS_CAP)
        duration_sec = float(args.webhook[1])
        total = max(concurrency, int(duration_sec * 2))
        print(f"[C9] Webhook: concurrency={concurrency}, duration_sec={duration_sec}, total_requests≈{total}")
        results = asyncio.run(run_webhook(base_url, secret, concurrency, total, use_aiohttp))
        elapsed = time.perf_counter() - start
        r = report("webhook", results, elapsed)
        all_reports.append(r)
        print(json.dumps(r, indent=2, ensure_ascii=False))

    if args.mixed:
        concurrency = int(args.mixed[0])
        duration_sec = float(args.mixed[1])
        total = max(concurrency * 2, int(duration_sec * 8))
        print(f"[C9] Mixed (read-only): concurrency={concurrency}, duration_sec={duration_sec}")
        results = asyncio.run(run_read_only(base_url, concurrency, total, use_aiohttp))
        elapsed = time.perf_counter() - start
        r = report("mixed_read", results, elapsed)
        all_reports.append(r)
        if secret:
            wtotal = max(2, int(duration_sec))
            wresults = asyncio.run(run_webhook(base_url, secret, 2, wtotal, use_aiohttp))
            r2 = report("mixed_webhook", wresults, time.perf_counter() - start - elapsed)
            all_reports.append(r2)
            print(json.dumps(r2, indent=2, ensure_ascii=False))
        print(json.dumps(r, indent=2, ensure_ascii=False))

    if not (args.read_only or args.webhook or args.mixed):
        # 默认：只读 10 并发 10 秒
        total = 100
        print(f"[C9] Default: read-only concurrency=10 total={total}")
        results = asyncio.run(run_read_only(base_url, 10, total, use_aiohttp))
        elapsed = time.perf_counter() - start
        r = report("read_only", results, elapsed)
        all_reports.append(r)
        print(json.dumps(r, indent=2, ensure_ascii=False))

    if args.output and all_reports:
        baseline_run = all_reports[0] if all_reports and all_reports[0].get("name") == "baseline" else None
        stress_reports = [r for r in all_reports if r.get("name") != "baseline"]
        payload = {
            "baseline_run": baseline_run,
            "stress_run": stress_reports[0] if len(stress_reports) == 1 else stress_reports,
            "reports": all_reports,
            "baseline_pass": baseline_report is not None and baseline_report.get("success_rate_pct") == 100,
            "environment": {"base_url": base_url},
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"Report written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
