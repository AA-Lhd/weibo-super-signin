# -*- coding: utf-8 -*-
"""
环境自动安装
============

把需要的依赖补齐，让它能在"什么都没有"的电脑上跑起来。

做三件事，按需执行，已经满足的会跳过：

1. 装 playwright 库（走清华源，失败自动退回官方源）
2. 检查浏览器通道。只要有 Chrome 或 Edge 能用，就**不下载** Chromium
3. 一个能用的浏览器都没有时，才下载 Playwright 自带的 Chromium（约 150 MB）

为什么优先用系统浏览器：Windows 10/11 自带 Edge，通常根本不用下载任何浏览器。

用法
----
    python setup_env.py
退出码：0 环境就绪，1 仍有缺失
"""

import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def line(msg=""):
    print(msg, flush=True)


def find_exe(paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return None


def ensure_pip():
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "--version"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            line("[1] pip 可用")
            return True
    except Exception:
        pass
    line("[1] pip 不可用，尝试用 ensurepip 修复 ...")
    try:
        subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"],
                       timeout=180)
    except Exception as exc:
        line("    ensurepip 失败: %s" % exc)
        return False
    r = subprocess.run([sys.executable, "-m", "pip", "--version"],
                       capture_output=True, text=True, timeout=60)
    ok = r.returncode == 0
    line("    结果: %s" % ("OK" if ok else "仍不可用"))
    return ok


def ensure_playwright():
    line()
    line("[2] playwright 库")
    try:
        import playwright  # noqa: F401
        line("    已安装，跳过")
        return True
    except Exception:
        pass

    for src_name, src in (("清华源", MIRROR), ("官方源", None)):
        cmd = [sys.executable, "-m", "pip", "install", "playwright"]
        if src:
            cmd += ["-i", src]
        line("    正在安装（%s）... 这一步可能要一两分钟" % src_name)
        try:
            r = subprocess.run(cmd, timeout=900)
        except Exception as exc:
            line("    安装异常: %s" % exc)
            continue
        if r.returncode == 0:
            try:
                import playwright  # noqa: F401
                line("    安装成功")
                return True
            except Exception:
                pass
        line("    %s 安装失败（返回码 %s），换个源重试" % (src_name, r.returncode))

    line("    结果: 安装失败")
    return False


def usable_channel_exists():
    """有 Chrome 或 Edge 就够用，不必下载 Chromium。"""
    line()
    line("[3] 浏览器通道")
    chrome = find_exe(CHROME_PATHS)
    edge = find_exe(EDGE_PATHS)
    line("    系统 Chrome : %s" % (chrome or "未找到"))
    line("    系统 Edge   : %s" % (edge or "未找到"))

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        for ch in ("chrome", "msedge"):
            try:
                b = p.chromium.launch(channel=ch, headless=True)
                b.close()
                line("    %s 启动测试: OK" % ch)
                line("    结论: 用系统浏览器即可，无需下载 Chromium")
                return True
            except Exception as exc:
                line("    %s 启动测试: 失败 %s"
                     % (ch, str(exc).split("\n")[0][:80]))

        # 看看自带 Chromium 在不在
        try:
            b = p.chromium.launch(headless=True)
            b.close()
            line("    自带 Chromium: OK")
            line("    结论: 环境已就绪")
            return True
        except Exception:
            line("    自带 Chromium: 未安装")

    line("    正在下载 Playwright 自带 Chromium（约 150 MB，请耐心等）...")
    try:
        r = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                           timeout=3600)
        if r.returncode != 0:
            line("    下载失败（返回码 %s）" % r.returncode)
            return False
    except Exception as exc:
        line("    下载异常: %s" % exc)
        return False

    line("    下载完成")
    return True


def main():
    line("=" * 58)
    line("微博超话签到 - 环境安装")
    line("目录: %s" % BASE_DIR)
    line("解释器: %s" % sys.executable)
    line("=" * 58)

    if not ensure_pip():
        line()
        line("结论：pip 不可用，无法继续")
        return 1

    if not ensure_playwright():
        line()
        line("结论：playwright 库装不上。检查网络后重试。")
        return 1

    if not usable_channel_exists():
        line()
        line("结论：没有可用浏览器，且自带 Chromium 下载失败。")
        line("      可以手工装一个 Edge/Chrome 后重跑本脚本。")
        return 1

    line()
    line("=" * 58)
    line("结论：环境就绪，可以运行「启动签到.bat」")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
