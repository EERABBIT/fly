#!/usr/bin/env python3
"""Daily K-line + moving averages for the holdings, stdlib only.

Reimplements quant_origin/em_api.py's eastmoney push2his call without pandas --
the rest of this pipeline has no third-party deps and the system python is
externally managed, so a venv just for a DataFrame wrapper isn't worth it.

Usage:
  python3 脚本/ma.py                 # all holdings in 数据源/持仓.json
  python3 脚本/ma.py 600893 002179   # explicit codes
"""
import json, os, subprocess, sys, urllib.parse, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # fly/
POS = os.path.join(BASE, "数据源", "持仓.json")
URL = "https://{h}push2his.eastmoney.com/api/qt/stock/kline/get"
# push2his rate-limits a single host hard (empty body / dropped connection after
# a handful of calls). Eastmoney serves the same data from numbered mirrors, so
# each retry hops to a different one.
HOSTS = ["", "1.", "7.", "19.", "29.", "33.", "58.", "82."]
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
MAS = (5, 10, 21, 34)   # the blogger's pyramid ladder


def secid(code):
    """6xxxxx -> Shanghai (1.), everything else -> Shenzhen (0.)"""
    return ("1." if code.startswith("6") else "0.") + code


def daily(code, beg="20260101", end="20301231", fqt=1, retry=len(HOSTS)):
    """Returns [(date, open, close, high, low, volume), ...] oldest first.

    Fetched through curl rather than urllib: push2his closes urllib's connection
    outright (RemoteDisconnected on every attempt, any headers) while the exact
    same URL via curl succeeds -- looks like TLS-fingerprint filtering.
    """
    q = urllib.parse.urlencode({
        "secid": secid(code), "klt": 101, "fqt": fqt, "beg": beg, "end": end,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    })
    for i in range(retry):
        cmd = ["curl", "-s", "-m", "15", "-A", UA,
               "-H", "Referer: https://quote.eastmoney.com/",
               URL.format(h=HOSTS[i % len(HOSTS)]) + "?" + q]
        try:
            raw = subprocess.run(cmd, capture_output=True, timeout=20).stdout
            data = json.loads(raw.decode()).get("data") or {}
            out = []
            for k in data.get("klines", []):
                p = k.split(",")
                out.append((p[0], float(p[1]), float(p[2]), float(p[3]),
                            float(p[4]), float(p[5])))
            if not out:
                raise ValueError("empty klines")
            return out, (data.get("name") or code)
        except Exception:
            if i == retry - 1:
                raise
            time.sleep(0.6 * (i + 1))
    return [], code


SINA = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "CN_MarketData.getKLineData?symbol={s}&scale=240&ma=no&datalen={n}")


def daily_sina(code, n=60):
    """Fallback source. push2his has stretches where every mirror answers with an
    empty body (curl: 52) no matter the host or headers -- sina still serves.
    Same 前复权 daily bars; spot-checked against push2his on 600893 (MA5/10/21/34
    and the 20-day range matched to the cent).
    """
    sym = ("sh" if code.startswith("6") else "sz") + code
    cmd = ["curl", "-s", "-m", "20", "-A", UA, SINA.format(s=sym, n=n)]
    raw = subprocess.run(cmd, capture_output=True, timeout=25).stdout.decode()
    rows = json.loads(raw)
    out = [(r["day"], float(r["open"]), float(r["close"]), float(r["high"]),
            float(r["low"]), float(r["volume"])) for r in rows]
    if not out:
        raise ValueError("empty klines")
    return out, code


def ma(closes, n):
    return sum(closes[-n:]) / n if len(closes) >= n else None


def report(code):
    try:
        bars, name = daily(code)
    except Exception as e:
        print(f"{code}  取数失败 {type(e).__name__}")
        return
    if not bars:
        print(f"{code}  无数据")
        return
    closes = [b[2] for b in bars]
    last = bars[-1]
    px = closes[-1]
    parts = []
    for n in MAS:
        v = ma(closes, n)
        parts.append(f"MA{n} {v:7.2f} ({(px/v-1)*100:+5.1f}%)" if v else f"MA{n}   --")
    # 20-day low/high for a破位 check
    lo20 = min(b[4] for b in bars[-20:])
    hi20 = max(b[3] for b in bars[-20:])
    newlow = "破20日新低" if last[4] <= lo20 + 1e-9 else ""
    print(f"{name}({code}) {last[0]} 收{px:7.2f}  " + "  ".join(parts)
          + f"  20日[{lo20:.2f},{hi20:.2f}] {newlow}")


if __name__ == "__main__":
    codes = sys.argv[1:] or [p[0] for p in json.load(open(POS, encoding="utf-8"))["positions"]]
    for c in codes:
        report(c)
        time.sleep(0.8)   # push2his drops back-to-back connections
