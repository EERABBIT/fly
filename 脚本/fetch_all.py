#!/usr/bin/env python3
"""Bulk-download WeChat article bodies into docs/<账号>/<YYYY>/<M>/.

Two sources:
  xlsx (default) -- 苍蝇的二级市场.xlsx, columns A=date B=title L=url
  --from-txt FILE -- lines of "M.D  https://mp.weixin.qq.com/s/..."; year from --year
"""
import argparse, glob, html, os, re, subprocess, sys, threading, time, xml.etree.ElementTree as ET, zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # fly/
XLSX = os.path.join(BASE, "数据源", "苍蝇的二级市场.xlsx")
DOCS = os.path.join(BASE, "docs")
FAILED = os.path.join(DOCS, "_failed.tsv")
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
BLOCK_MARKERS = ("未知错误", "失效的验证页面", "环境异常")


def read_rows():
    """Parse the xlsx with stdlib only; return dicts keyed by column letter."""
    z = zipfile.ZipFile(XLSX)
    shared = ["".join(t.text or "" for t in si.iter(NS + "t"))
              for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
    sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml")).find(NS + "sheetData")
    out = []
    for row in list(sheet)[1:]:  # skip header
        d = {}
        for c in row:
            v = c.find(NS + "v")
            if v is None or v.text is None:
                continue
            col = re.sub(r"\d+$", "", c.get("r", ""))  # "A2" -> "A"
            d[col] = shared[int(v.text)] if c.get("t") == "s" else v.text
        if d.get("L"):
            out.append(d)
    return out


def read_txt(path, year):
    """Parse "8.25 <url>" lines into the same dict shape as read_rows(); title fills in
    from the fetched page later, so B is left empty here."""
    out = []
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\s*(\d{1,2})\.(\d{1,2})\s+(https?://\S+)", line)
        if m:
            mo, da, url = m.groups()
            # poc_token is a one-shot access token copied out of WeChat; once expired it
            # makes the request fail, while the bare /s/<hash> link keeps working.
            url = re.sub(r"[?&]poc_token=[^&]*", "", url)
            out.append({"A": f"{year}-{int(mo):02d}-{int(da):02d}", "L": url})
    return out


def safe_name(title, url):
    name = re.sub(r'[/\\:*?"<>|]', "", title or "")
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if not name:
        m = re.search(r"(?:mid|sn)=([0-9A-Za-z_-]+)", url)
        name = m.group(1) if m else "untitled"
    return name[:60]


def month_dir(account, date):
    """docs/<账号>/<YYYY>/<M>  -- month unpadded, per the requested layout."""
    return os.path.join(DOCS, account, date[:4], str(int(date[5:7])))


def target_path(date, title, url, taken, account):
    """Reserve a path unique among *this run's* rows. Dedupe only against `taken`, never
    against files on disk -- row order is deterministic, so each row maps to the same name
    every run, which is what makes skip-if-exists idempotent."""
    stem = os.path.join(month_dir(account, date), f"{date}_{safe_name(title, url)}")
    path, n = stem + ".md", 1
    while path in taken:
        n += 1
        path = f"{stem}-{n}.md"
    taken.add(path)
    return path


def extract(page):
    m = re.search(r"var msg_title\s*=\s*'(.*?)'", page)
    if not m:
        m = re.search(r'property="og:title"\s+content="(.*?)"', page)
    title = html.unescape(m.group(1)).strip() if m else ""
    body_m = re.search(r'id="js_content".*?>(.*)', page, re.S)
    if not body_m:
        return title, ""
    b = re.sub(r"<script.*?</script>", "", body_m.group(1), flags=re.S)
    b = re.sub(r"<[^>]+>", "\n", b)
    b = html.unescape(b)
    b = re.sub(r"[ \t\xa0]+", " ", b)
    return title, re.sub(r"\n\s*\n\s*\n+", "\n\n", b).strip()


def fetch(url):
    """Return (title, body) or raise RuntimeError with a short reason."""
    p = subprocess.run(["curl", "-s", "-L", "--compressed", "-A", UA, "--max-time", "30",
                        "-w", "\n%{http_code}", url], capture_output=True, text=True, errors="replace")
    page, _, code = p.stdout.rpartition("\n")
    if code.strip() != "200":
        raise RuntimeError("http=" + (code.strip() or "none"))
    for mk in BLOCK_MARKERS:
        if mk in page:
            raise RuntimeError(mk)
    if 'id="js_content"' not in page:
        raise RuntimeError("no_js_content")
    title, body = extract(page)
    if len(body) < 50:
        raise RuntimeError("short_body")
    return title, body


class Runner:
    def __init__(self, args):
        self.args, self.lock = args, threading.Lock()
        self.done = self.ok = self.fail = self.streak = 0
        self.failures = []

    def work(self, job):
        """One article, with exponential backoff; returns after success or 3 failed tries."""
        row, path = job
        url, reason = row["L"], "unknown"
        for delay in (10, 30, 60, None):
            try:
                time.sleep(self.args.delay)
                title, body = fetch(url)
            except Exception as e:
                reason = str(e)[:80]
                if delay is None:
                    break
                time.sleep(delay)
                continue
            head = f"# {title or row.get('B','')}\n\n"
            if path is None:  # txt source: no title known up front, so name it post-fetch
                with self.lock:
                    path = target_path(row["_d"], title, url, self.taken, self.args.account)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(head + body + "\n")
            self.finish(True, row, reason)
            return
        self.finish(False, row, reason)

    def finish(self, good, row, reason):
        with self.lock:
            self.done += 1
            if good:
                self.ok, self.streak = self.ok + 1, 0
            else:
                self.fail, self.streak = self.fail + 1, self.streak + 1
                self.failures.append((row["_d"], row.get("B", ""), row["L"], reason))
            if self.done % 50 == 0:
                print(f"{self.done}/{self.total} ok={self.ok} fail={self.fail}", flush=True)
            ban = self.streak > 10
            if ban:
                self.streak = 0
        if ban:  # long streak => assume temporary IP ban, back off outside the lock
            time.sleep(300)

    def run(self, jobs):
        self.total = len(jobs)
        q, qlock = list(reversed(jobs)), threading.Lock()

        def loop():
            while True:
                with qlock:
                    if not q:
                        return
                    job = q.pop()
                self.work(job)

        threads = [threading.Thread(target=loop) for _ in range(max(1, self.args.workers))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2020-01-01")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--account", default="苍蝇的二级市场", help="docs/ 下的顶层文件夹名")
    ap.add_argument("--from-txt", help='读 "8.25 <url>" 格式的链接清单，替代 xlsx')
    ap.add_argument("--year", type=int, default=2026, help="--from-txt 的年份")
    args = ap.parse_args()

    rows = read_txt(args.from_txt, args.year) if args.from_txt else read_rows()
    if args.retry_failed:
        want = set()
        if os.path.exists(FAILED):
            with open(FAILED, encoding="utf-8") as f:
                want = {ln.split("\t")[2] for ln in f.read().splitlines() if ln.count("\t") >= 3}
        rows = [r for r in rows if r["L"] in want]
    considered, jobs, skipped, taken = 0, [], 0, set()
    for r in rows:
        r["_d"] = (r.get("A") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["_d"]) or r["_d"] < args.since:
            continue
        considered += 1
        if args.from_txt:
            # Title is unknown before fetching, so skip-if-exists keys on the date prefix
            # instead of the full filename (this blogger posts at most once a day).
            if glob.glob(os.path.join(month_dir(args.account, r["_d"]), r["_d"] + "_*.md")):
                skipped += 1
            else:
                jobs.append((r, None))
        else:
            path = target_path(r["_d"], r.get("B", ""), r["L"], taken, args.account)
            if os.path.exists(path):  # resumable: never re-download
                skipped += 1
            else:
                jobs.append((r, path))
        if args.limit and considered >= args.limit:
            break

    runner = Runner(args)
    runner.taken = taken
    if jobs:
        runner.run(jobs)
    os.makedirs(DOCS, exist_ok=True)
    with open(FAILED, "w", encoding="utf-8") as f:  # rewritten each run
        for rec in runner.failures:
            f.write("\t".join(x.replace("\t", " ") for x in rec) + "\n")

    print(f"considered: {considered}")
    print(f"downloaded: {runner.ok}")
    print(f"skipped-existing: {skipped}")
    print(f"failed: {runner.fail}")


if __name__ == "__main__":
    main()
