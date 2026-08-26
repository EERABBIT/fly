# 微信公众号文章抓取

## 工具

`fetch_wechat_articles.py` — 根据文章链接抓取微信公众号文章。

```bash
# 抓取单篇
python3 fetch_wechat_articles.py "https://mp.weixin.qq.com/s/xxxxx"

# 抓取多篇
python3 fetch_wechat_articles.py \
  "https://mp.weixin.qq.com/s/url1" \
  "https://mp.weixin.qq.com/s/url2"
```

**工作原理**：curl + UA 模拟直接请求文章页，解析出正文和元信息（标题/作者/发布时间/摘要）。只依赖标准库。

---

## 如何获取文章链接

1. 在微信里打开目标文章
2. 点右上角 `...` → 复制链接
3. 把链接作为参数传给脚本

---

## 目录结构

```
wechat_articles/
├── index.json          # 本次抓取的文章元数据（每次运行会覆盖）
├── raw/                # 原始 HTML
│   └── 01-*.html
└── 01-*.md             # 可读的 Markdown
```

---

## 局限性

- 无法自动获取历史文章列表——微信没有公开接口，必须手动提供链接
- `index.json` 每次运行会被覆盖，只记录当次抓取的文章；需要保留历史请先备份

---

## 已知有效文章（截至 2026-08-14）

| 日期 | 标题 | URL |
|------|------|-----|
| 2026-05-13 | 仓位配置 | https://mp.weixin.qq.com/s/uQIuQmoMwBqTlWzpFyhtPw |
| 2026-05-12 | 各大ETF，马上要被卖完了 | https://mp.weixin.qq.com/s/aR35gfIRqvny98hk4AodfQ |
| 2026-05-11 | 直升机的估值 | https://mp.weixin.qq.com/s/NsTJgFH-fjIw4vfE5E614A |
| 2026-05-09 | 谈谈京D方目标利润 | https://mp.weixin.qq.com/s/YkGSeQv_n-3Xupt9WE33-g |
