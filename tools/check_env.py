# -*- coding: utf-8 -*-
"""
环境自检
========

用途
----
无声检查本机是否具备运行微博超话签到的条件，并实际启动每个可用的浏览器
通道做验证（不是只看文件是否存在）。换新电脑、排查异常时先跑这个。

它回答三个问题：
1. Python 能不能用、版本多少
2. playwright 库装了没有
3. 能用哪个浏览器跑（Chrome / Edge / Playwright 自带 Chromium）

浏览器优先级：Chrome > Edge > 自带 Chromium。
Edge 的存在意义很大 —— Windows 10/11 自带 Edge，所以哪怕目标电脑
什么开发环境都没有，也不一定需要额外装浏览器。

用法
----
    python check_env.py
退出码：0 有可用浏览器，1 一个都没有
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]

EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

CHANNEL_PRIORITY = ["chrome", "msedge", "bundled"]


def line(msg=""):
    print(msg, flush=True)


def check_python():
    line("[1] Python")
    line("    版本   : %s" % sys.version.split()[0])
    line("    解释器 : %s" % sys.executable)
    ok = sys.version_info >= (3, 8)
    line("    结果   : %s" % ("OK" if ok else "版本过低，playwright 需要 3.8+"))
    return ok


def check_playwright():
    line()
    line("[2] playwright 库")
    try:
        import playwright  # noqa: F401
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception as exc:
        line("    结果   : 未安装或不可用 -> %s" % exc)
        line("    处理   : 运行 setup_env.py 自动安装")
        return False
    try:
        from importlib.metadata import version
        ver = version("playwright")
    except Exception:
        ver = "未知"
    line("    版本   : %s" % ver)
    line("    结果   : OK")
    return True


def find_exe(paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return None


def check_browsers():
    """实际启动各通道验证，不是只看文件在不在。"""
    line()
    line("[3] 浏览器通道（逐个实际启动验证）")

    line("    -- 文件检测 --")
    chrome = find_exe(CHROME_PATHS)
    edge = find_exe(EDGE_PATHS)
    line("    系统 Chrome : %s" % (chrome or "未找到"))
    line("    系统 Edge   : %s" % (edge or "未找到"))
    bundled_dir = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright")
    bundled = []
    if os.path.isdir(bundled_dir):
        bundled = [d for d in os.listdir(bundled_dir) if d.startswith("chromium")]
    line("    自带 Chromium: %s" % (", ".join(bundled) if bundled else "未安装"))

    line("    -- 启动测试 --")
    from playwright.sync_api import sync_playwright

    result = {}
    with sync_playwright() as p:
        for ch in ("chrome", "msedge"):
            try:
                b = p.chromium.launch(channel=ch)
                b.close()
                result[ch] = "OK"
            except Exception as exc:
                result[ch] = "FAIL: %s" % str(exc).split("\n")[0][:110]
        try:
            b = p.chromium.launch()
            b.close()
            result["bundled"] = "OK"
        except Exception as exc:
            result["bundled"] = "FAIL: %s" % str(exc).split("\n")[0][:110]

    for ch in CHANNEL_PRIORITY:
        line("    %-9s : %s" % (ch, result.get(ch, "未测试")))

    usable = [c for c in CHANNEL_PRIORITY if result.get(c) == "OK"]
    line()
    if usable:
        line("    可用通道 : %s" % ", ".join(usable))
        line("    将使用   : %s" % usable[0])
    else:
        line("    可用通道 : 无")
        line("    处理     : 运行 setup_env.py 自动装浏览器"
             "（没有 Python 就先跑 启动签到.bat）")
    return usable


def main():
    line("=" * 58)
    line("微博超话签到 - 环境自检")
    line("目录: %s" % BASE_DIR)
    line("=" * 58)
    py_ok = check_python()
    pw_ok = check_playwright()
    if not (py_ok and pw_ok):
        line()
        line("结论：环境不完整，请先跑 setup_env.py")
        return 1
    usable = check_browsers()
    line()
    line("=" * 58)
    if usable:
        line("结论：可以运行微博超话签到")
        return 0
    line("结论：没有可用浏览器，无法运行")
    return 1


if __name__ == "__main__":
    sys.exit(main())
