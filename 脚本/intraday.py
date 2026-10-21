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


def quote(s):
    """实时行情 hq.sinajs：(名称, 昨收, 现价, 高, 低, 成交量股, 日期)。
    sina 日线盘中不含当天未完成K线，所以现价/高低必须从这里取。"""
    raw = subprocess.run(["curl", "-s", "-m", "10", "-H", "Referer: https://finance.sina.com.cn",
                          f"https://hq.sinajs.cn/list={s}"], capture_output=True, timeout=15).stdout
    f = raw.decode("gbk", "ignore").split('"')[1].split(",")
    return f[0], float(f[2]), float(f[3]), float(f[4]), float(f[5]), float(f[8]), f[30]


def line(s, name, today):
    d = [x for x in bars(s, 240, 70) if x["day"][:10] < today]   # 只要已收盘日线
    if len(d) < 61:
        return f"{name:<8} 取数失败"
    _, pc, px, hi, lo, vol_today, qday = quote(s)
    hist = [float(x["close"]) for x in d]
    if qday != today or px == 0:
        # 盘前/休市：hq 里还是上一交易日的行情，它的"昨收"是前天的；
        # 现价改用最近一根已收盘日线，均线则去掉这根，和盘中口径一致
        px = hi = lo = hist[-1]
        pc = hist[-2]
        vol_today = float(d[-1]["volume"])
        d, hist = d[:-1], hist[:-1]
    ma = {n: sum(hist[-n:]) / n for n in (5, 10, 21, 34, 60)}
    slope60 = (ma[60] / (sum(hist[-65:-5]) / 60) - 1) * 100
    pv = float(d[-1]["volume"])
    m30 = [x for x in bars(s, 30, 9) if x["day"].startswith(today)]
    m5 = [x for x in bars(s, 5, 48) if x["day"].startswith(today)]
    # 30分钟路径 + 当前未走完的那根（用最新5分钟收盘补上）
    pts = [(x["day"][11:16], float(x["close"])) for x in m30]
    if m5 and (not m30 or m5[-1]["day"] > m30[-1]["day"]):
        pts.append((m5[-1]["day"][11:16] + "*", float(m5[-1]["close"])))
    path = " ".join(f"{t}{(c / pc - 1) * 100:+.1f}" for t, c in pts)
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
    today = time.strftime("%Y-%m-%d")
    try:
        asof = quote("sh000001")[6]
    except Exception:
        asof = "?"
    stale = "" if asof == today else "  ⚠ 今天无行情（盘前/休市），以下为最近收盘状态"
    print(time.strftime("%H:%M"), f"快照（偏离单位%：现价对已收盘均线；路径=30分钟收盘相对昨收，*为当前未走完那根）{stale}")
    for s, n in GAUGES + held + [(c, c) for c in extra]:
        try:
            print(line(sym(s), n, today))
        except Exception as e:
            print(f"{n:<8} 取数失败 {type(e).__name__}")
        time.sleep(0.25)


if __name__ == "__main__":
    main()
