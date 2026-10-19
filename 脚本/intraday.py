#!/usr/bin/env python3
"""盘中快照：指数/风向标/持仓的当日分时节奏 + 日线均线位置，一屏输出。

给 指南3-盘中监控SOP 用：每次触发只读这份输出，不再现写取数代码。
数据走 sina（push2his 盘中限流太狠），纯标准库。

Usage:
  python3 脚本/intraday.py              # 风向标 + 持仓.json 全部持仓
  python3 脚本/intraday.py 600760 302132  # 额外加观察票
"""
import json, os, subprocess, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POS = os.path.join(BASE, "数据源", "持仓.json")
URL = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
       "CN_MarketData.getKLineData?symbol={s}&scale={k}&ma=no&datalen={n}")
GAUGES = [("sz399006", "创业板"), ("sh000688", "科创50"), ("sh000852", "中证1000"),
          ("sz399303", "国证2000"), ("sz399967", "中证军工"), ("sh560780", "半导体设备ETF")]


def sym(code):
    return code if code[:2] in ("sh", "sz") else ("sh" if code.startswith(("6", "5")) else "sz") + code


def bars(s, k, n):
    raw = subprocess.run(["curl", "-s", "-m", "15", "-A", "Mozilla/5.0", URL.format(s=s, k=k, n=n)],
                         capture_output=True, timeout=20).stdout.decode()
    return json.loads(raw or "[]")


def line(s, name):
    d = bars(s, 240, 70)
    if len(d) < 61:
        return f"{name:<8} 取数失败"
    today = d[-1]["day"][:10]
    # 盘中 sina 日线最后一根就是今天的未完成K线；昨收取倒数第二根
    cl = [float(x["close"]) for x in d]
    pc, px = cl[-2], cl[-1]
    hist = cl[:-1]                       # 均线只用已收盘的K线
    ma = {n: sum(hist[-n:]) / n for n in (5, 10, 21, 34, 60)}
    slope60 = (ma[60] / (sum(hist[-65:-5]) / 60) - 1) * 100
    pv = float(d[-2]["volume"])
    m30 = [x for x in bars(s, 30, 9) if x["day"].startswith(today)]
    path = " ".join(f'{x["day"][11:16]}{(float(x["close"]) / pc - 1) * 100:+.1f}' for x in m30)
    vol_today = sum(float(x["volume"]) for x in m30)
    hi = max(float(x["high"]) for x in m30) if m30 else px
    lo = min(float(x["low"]) for x in m30) if m30 else px
    pos = " ".join(f"{n}:{(px / v - 1) * 100:+.1f}" for n, v in ma.items())
    return (f"{name:<8} 现{(px / pc - 1) * 100:+.2f}% 高{(hi / pc - 1) * 100:+.1f} 低{(lo / pc - 1) * 100:+.1f}"
            f" 量/昨{vol_today / pv:.2f} | 偏离 {pos} | 60线斜率{slope60:+.1f}%\n"
            f"{'':<10}{path}")


def main():
    extra = [a for a in sys.argv[1:] if not a.startswith("-")]
    try:
        held = [(p[0], p[1]) for p in json.load(open(POS, encoding="utf-8"))["positions"]]
    except Exception:
        held = []
    try:
        asof = bars("sh000001", 240, 1)[-1]["day"][:10]
    except Exception:
        asof = "?"
    stale = "" if asof == time.strftime("%Y-%m-%d") else "  ⚠ 数据日期非今天（盘前/休市），以下为最近交易日收盘状态"
    print(time.strftime("%H:%M"), f"快照 数据日{asof}（偏离单位%；路径为30分钟收盘相对昨收）{stale}")
    for s, n in GAUGES + held + [(c, c) for c in extra]:
        try:
            print(line(sym(s), n))
        except Exception as e:
            print(f"{n:<8} 取数失败 {type(e).__name__}")
        time.sleep(0.25)


if __name__ == "__main__":
    main()
