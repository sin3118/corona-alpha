#!/usr/bin/env python3
"""매일 아침 전날 미국 시황 + 관심 종목(VOO, QQQ, UNH) 데이터 수집.

숫자만 계산한다. 해석과 뉴스 요약은 이 출력을 읽는 Claude가 한다.

출력:
  reports/daily/<YYYY-MM-DD>/data.json   – 전체 숫자
  reports/daily/<YYYY-MM-DD>/data.md     – 사람이 읽는 표
  reports/daily/<YYYY-MM-DD>/regime/     – 시장 점검 skill 원본 리포트

필요한 네트워크: query1.finance.yahoo.com, tradermonty.github.io, raw.githubusercontent.com
사용: python3 scripts/daily_us_review.py [--watch VOO,QQQ,UNH]
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, ".claude", "skills")
UA = {"User-Agent": "Mozilla/5.0"}

MARKET = {
    "^GSPC": "S&P 500", "^IXIC": "나스닥 종합", "^DJI": "다우", "^RUT": "러셀 2000",
    "^VIX": "VIX", "^TNX": "미 10년 금리(%)", "KRW=X": "달러/원",
}
SECTORS = {
    "XLK": "기술", "SMH": "반도체", "XLV": "헬스케어", "XLF": "금융", "XLE": "에너지",
    "XLY": "임의소비재", "XLP": "필수소비재", "XLI": "산업재", "XLU": "유틸리티",
}
# 종목별 사용자 지정 관찰 가격 (지지/저항). 필요하면 여기서 고친다.
LEVELS = {
    "UNH": {"지지(11/23 장중 저점)": 319.13, "52주 저점": 255.97},
}


def fetch(sym: str, rng: str = "2y", iv: str = "1d") -> dict:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}"
           f"?range={rng}&interval={iv}&events=div")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        res = json.load(r)["chart"]["result"][0]
    m = res["meta"]
    q = res["indicators"]["quote"][0]
    rows = []
    for t, o, h, l, c, v in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"], q["volume"]):
        rows.append({"date": dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat(),
                     "o": o, "h": h, "l": l, "c": c, "v": v})
    # 마지막 봉 종가가 비어 있으면 meta 의 현재가로 채운다 (Yahoo 가 자주 그럼)
    if rows and rows[-1]["c"] is None and m.get("regularMarketPrice"):
        rows[-1].update(c=m["regularMarketPrice"], h=m.get("regularMarketDayHigh"),
                        l=m.get("regularMarketDayLow"), v=m.get("regularMarketVolume"))
    rows = [x for x in rows if x["c"] is not None]
    divs = sorted((int(k), v["amount"]) for k, v in res.get("events", {}).get("dividends", {}).items())
    return {"rows": rows, "meta": m, "divs": divs}


def rsi(closes: list[float], n: int = 14) -> list[float]:
    if len(closes) <= n:
        return []
    g = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    lo = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    ag, al = sum(g[:n]) / n, sum(lo[:n]) / n
    out = []
    for i in range(n, len(g)):
        ag = (ag * (n - 1) + g[i]) / n
        al = (al * (n - 1) + lo[i]) / n
        out.append(100 - 100 / (1 + ag / al) if al else 100.0)
    return out


def pct(a: float, b: float) -> float:
    return round((a / b - 1) * 100, 2)


def stats(sym: str) -> dict:
    d = fetch(sym)
    rows = d["rows"]
    c = [x["c"] for x in rows]
    last = c[-1]
    ma = lambda k: sum(c[-k:]) / min(k, len(c))  # noqa: E731
    yr = [x for x in rows[-252:] if x["h"] and x["l"]]
    hi, lo = max(x["h"] for x in yr), min(x["l"] for x in yr)
    hl = [x for x in rows if x["h"] and x["l"]]
    trs = [max(hl[i]["h"] - hl[i]["l"], abs(hl[i]["h"] - hl[i - 1]["c"]), abs(hl[i]["l"] - hl[i - 1]["c"]))
           for i in range(len(hl) - 14, len(hl))]
    atr = sum(trs) / 14
    r = rsi(c)
    vols = [x["v"] for x in rows if x["v"]]
    out = {
        "symbol": sym, "date": rows[-1]["date"], "close": round(last, 2),
        "chg_1d": pct(last, c[-2]), "chg_1w": pct(last, c[-6]), "chg_1m": pct(last, c[-22]),
        "chg_3m": pct(last, c[-64]), "chg_1y": pct(last, c[-253]) if len(c) > 253 else None,
        "ma20": round(ma(20), 2), "ma50": round(ma(50), 2), "ma200": round(ma(200), 2),
        "above_ma20": last > ma(20), "above_ma50": last > ma(50), "above_ma200": last > ma(200),
        "hi_52w": round(hi, 2), "lo_52w": round(lo, 2),
        "from_hi_52w": pct(last, hi), "from_lo_52w": pct(last, lo),
        "atr14": round(atr, 2), "atr_pct": round(atr / last * 100, 2),
        "rsi14": round(r[-1], 1) if r else None,
        "rsi14_prev": round(r[-2], 1) if len(r) > 1 else None,
        "rsi14_last5": [round(x, 1) for x in r[-5:]],
        "low_20d": round(min(x["l"] for x in rows[-20:] if x["l"]), 2),
        "high_20d": round(max(x["h"] for x in rows[-20:] if x["h"]), 2),
        "vol_ratio_50d": round(vols[-1] / (sum(vols[-51:-1]) / 50), 2) if len(vols) > 51 else None,
    }
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=365)).timestamp()
    ttm = sum(a for t, a in d["divs"] if t > cutoff)
    out["div_ttm"] = round(ttm, 4)
    out["div_yield_pct"] = round(ttm / last * 100, 2) if ttm else 0.0
    try:
        w = fetch(sym, "10y", "1wk")
        wr = rsi([x["c"] for x in w["rows"]])
        out["rsi14_weekly"] = round(wr[-1], 1) if wr else None
    except Exception as e:  # noqa: BLE001
        out["rsi14_weekly"] = None
        out["weekly_error"] = str(e)
    return out


def quick(sym: str) -> dict:
    d = fetch(sym, "1y")
    c = [x["c"] for x in d["rows"]]
    last = c[-1]
    return {"symbol": sym, "date": d["rows"][-1]["date"], "close": round(last, 2),
            "chg_1d": pct(last, c[-2]), "chg_1w": pct(last, c[-6]), "chg_1m": pct(last, c[-22]),
            "from_hi": pct(last, max(c)),
            "above_ma50": last > sum(c[-50:]) / 50, "above_ma200": last > sum(c[-200:]) / min(200, len(c))}


def run_regime(outdir: str) -> dict:
    os.makedirs(outdir, exist_ok=True)
    py = sys.executable
    res: dict = {}
    for name, script in [("breadth", "market-breadth-analyzer/scripts/market_breadth_analyzer.py"),
                         ("uptrend", "uptrend-analyzer/scripts/uptrend_analyzer.py")]:
        p = subprocess.run([py, os.path.join(SKILLS, script), "--output-dir", outdir],
                           capture_output=True, text=True, timeout=600)
        if p.returncode != 0:
            res[name] = {"error": (p.stderr or p.stdout)[-500:]}
    b = sorted(glob.glob(os.path.join(outdir, "market_breadth_????-??-??_??????.json")))
    u = sorted(glob.glob(os.path.join(outdir, "uptrend_analysis_????-??-??_??????.json")))
    for key, files in (("breadth", b), ("uptrend", u)):
        if files:
            j = json.load(open(files[-1]))
            comp = j.get("composite") or {}
            res[key] = {"score": comp.get("composite_score", j.get("composite_score")),
                        "zone": comp.get("zone") or comp.get("health_zone") or j.get("zone"),
                        "exposure": comp.get("exposure_guidance") or comp.get("equity_exposure"),
                        "file": os.path.relpath(files[-1], ROOT)}
    if b and u:
        p = subprocess.run([py, os.path.join(SKILLS, "exposure-coach/scripts/calculate_exposure.py"),
                            "--breadth", b[-1], "--uptrend", u[-1], "--output-dir", outdir],
                           capture_output=True, text=True, timeout=300)
        e = sorted(glob.glob(os.path.join(outdir, "exposure_posture_*.json")))
        if e:
            j = json.load(open(e[-1]))
            res["exposure"] = {k: j.get(k) for k in ("recommendation", "confidence", "exposure_ceiling_pct",
                                                      "inputs_provided", "inputs_missing")}
        else:
            res["exposure"] = {"error": (p.stderr or p.stdout)[-500:]}
    return res


def flags(s: dict, bench: dict | None) -> list[str]:
    f = []
    r = s.get("rsi14")
    if r is not None:
        if r < 30:
            f.append(f"RSI {r} 과매도")
        elif r > 70:
            f.append(f"RSI {r} 과매수")
        rp = s.get("rsi14_prev")
        if rp is not None and (rp < 50) != (r < 50):
            f.append(f"RSI 50선 {'상향' if r >= 50 else '하향'} 돌파 ({rp}→{r})")
    for k, n in (("ma20", "20일"), ("ma50", "50일"), ("ma200", "200일")):
        f.append(f"{n}선 {'위' if s['above_' + k] else '아래'}")
    if abs(s["chg_1d"]) >= 2 * s["atr_pct"]:
        f.append(f"전일 변동 {s['chg_1d']:+}% 가 평소 변동폭(ATR {s['atr_pct']}%)의 2배 이상")
    if s.get("vol_ratio_50d") and s["vol_ratio_50d"] >= 2:
        f.append(f"거래량 평소의 {s['vol_ratio_50d']}배")
    if bench and s["symbol"] != bench["symbol"]:
        f.append(f"VOO 대비 1개월 {s['chg_1m'] - bench['chg_1m']:+.1f}%p")
    for label, lv in LEVELS.get(s["symbol"], {}).items():
        f.append(f"{label} ${lv}: 현재가가 {'위' if s['close'] >= lv else '아래(이탈)'} ({pct(s['close'], lv):+}%)")
    return f


def to_md(data: dict) -> str:
    L = [f"# 미국 시황 데이터 — {data['as_of_kst']} (KST) 생성", ""]
    L.append("## 시장 지표")
    L.append("| 지표 | 값 | 1일 | 1주 | 1달 | 고점대비 | MA50 | MA200 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for grp in ("market", "sectors"):
        for sym, q in data[grp].items():
            if "error" in q:
                L.append(f"| {q.get('name', sym)} | 오류 | | | | | | |")
                continue
            L.append(f"| {q['name']} ({sym}) | {q['close']} | {q['chg_1d']:+}% | {q['chg_1w']:+}% | {q['chg_1m']:+}% | "
                     f"{q['from_hi']:+}% | {'위' if q['above_ma50'] else '아래'} | {'위' if q['above_ma200'] else '아래'} |")
    L += ["", "## 시장 점검 (market-breadth / uptrend / exposure-coach)", "```",
          json.dumps(data["regime"], ensure_ascii=False, indent=2), "```", "", "## 관심 종목"]
    for sym, s in data["watch"].items():
        if "error" in s:
            L += [f"### {sym}: 오류 {s['error']}", ""]
            continue
        L += [f"### {sym} — ${s['close']} ({s['date']}, {s['chg_1d']:+}%)",
              f"- 1주 {s['chg_1w']:+}% / 1달 {s['chg_1m']:+}% / 3달 {s['chg_3m']:+}% / 1년 {s['chg_1y']}%",
              f"- MA20 {s['ma20']} / MA50 {s['ma50']} / MA200 {s['ma200']}",
              f"- 52주 고점 {s['hi_52w']} ({s['from_hi_52w']:+}%), 저점 {s['lo_52w']} ({s['from_lo_52w']:+}%)",
              f"- RSI14 일간 {s['rsi14']} (최근5 {s['rsi14_last5']}), 주간 {s.get('rsi14_weekly')}",
              f"- ATR14 {s['atr14']} ({s['atr_pct']}%), 20일 범위 {s['low_20d']}~{s['high_20d']}, 거래량비 {s['vol_ratio_50d']}",
              f"- 배당률(최근 1년) {s['div_yield_pct']}%",
              "- 신호: " + "; ".join(s["flags"]), ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", default="VOO,QQQ,UNH")
    ap.add_argument("--skip-regime", action="store_true")
    a = ap.parse_args()
    kst = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    outdir = os.path.join(ROOT, "reports", "daily", kst.date().isoformat())
    os.makedirs(outdir, exist_ok=True)
    data: dict = {"as_of_kst": kst.strftime("%Y-%m-%d %H:%M"), "market": {}, "sectors": {}, "watch": {}}
    for grp, mp in (("market", MARKET), ("sectors", SECTORS)):
        for sym, name in mp.items():
            try:
                data[grp][sym] = {"name": name, **quick(sym)}
            except Exception as e:  # noqa: BLE001
                data[grp][sym] = {"name": name, "error": str(e)}
    bench = None
    for sym in [x.strip().upper() for x in a.watch.split(",") if x.strip()]:
        try:
            s = stats(sym)
            if sym == "VOO":
                bench = s
            data["watch"][sym] = s
        except Exception as e:  # noqa: BLE001
            data["watch"][sym] = {"error": str(e)}
    if bench is None and "VOO" not in data["watch"]:
        try:
            bench = stats("VOO")
        except Exception:  # noqa: BLE001
            pass
    for s in data["watch"].values():
        if "error" not in s:
            s["flags"] = flags(s, bench)
    data["regime"] = {} if a.skip_regime else run_regime(os.path.join(outdir, "regime"))
    json.dump(data, open(os.path.join(outdir, "data.json"), "w"), ensure_ascii=False, indent=2)
    md = to_md(data)
    open(os.path.join(outdir, "data.md"), "w").write(md)
    print(md)
    print(f"\n[saved] {os.path.relpath(outdir, ROOT)}/data.json, data.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
