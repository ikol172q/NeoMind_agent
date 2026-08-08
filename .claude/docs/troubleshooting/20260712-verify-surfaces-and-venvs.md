# 2026-07-12 — 交付只有 curl+import；烟测跑错 venv 全 SKIP；包只装了一个 venv

**WRONG**
- open-core 解耦交付时只给 curl 200 + import OK 就报"完成"，三个用户表面（CLI/Telegram/browser）一个没真测。
- 在 `~/.neomind_fin_venv` 跑 `cross_mode_boot_smoke.py` → 缺 iterm2 → SKIP=3，差点被当验证证据。
- `neomind-dashboard` 只 editable 装进 fin_venv → CLI(.venv) 的 `fin_provider` 会**静默回退** baseline（无报错的功能降级）。

**RIGHT**
- boot 烟测用 `.venv/bin/python`（有 iterm2）；pytest/服务用 fin_venv；**SKIP≠PASS**。
- editable 包（neomind + neomind-dashboard）**两个 venv 都装**，装完各自 `fin_package()` 验证解析结果。
- 宣布完成前三表面真验：8001 kickstart 重启+browser 真点（playwright）、`docker restart neomind-telegram`（bind-mount 代码，重启才生效）+Telethon 真发真收（session 在 `~/.config/neomind-tester/`）、CLI 真 boot。

**WHY** 双 venv 分工不同，只验一个=另一半是盲区；SKIP 是"没测"不是"通过"；bind-mount 容器不重启永远跑旧代码。
