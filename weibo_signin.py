# -*- coding: utf-8 -*-
"""
微博超话每日签到（可迁移版）
============================

这个目录是自包含的：拷到任意一台 Windows 电脑上，首次双击「启动签到.bat」，
脚本会自动检测环境、引导你登录微博一次，之后就一直复用这个登录态。

首次运行会做什么
----------------
1. 挑选可用的浏览器（Chrome > Edge > 自带 Chromium，逐个实际启动验证）
2. 检测登录态。没登录 -> 弹出浏览器窗口，提示你手动登录微博
3. 登录成功后，登录态由浏览器自己保存在 profile\\ 目录里
4. 顺便把「每天 00:00 自动签到」的计划任务注册到这台电脑上
5. 当天就完成一次签到

之后再运行：直接签到，不再需要登录（除非登录态过期）。

为什么换电脑必须重新登录
------------------------
浏览器的 cookie 用 Windows DPAPI 加密，密钥绑定"哪台电脑的哪个用户"。
把 profile 目录复制到别的电脑，cookie 解不开，浏览器视为未登录。
所以"换机重新登录一次"不是妥协，是唯一可行的做法。

为什么不用日常浏览器的登录态
----------------------------
Chrome 127+ 启用了 App-Bound Encryption，cookie 无法离线解密导出；
且浏览器运行时其配置目录被独占。所以只能用本目录下的独立 profile。

签到按钮怎么定位（2026-09-20 实测于周深超话）
---------------------------------------------
超话头部「发帖 / 关注 / 签到」一行，y≈323。

* 未签到：DIV，class 只含 `_signBtnOverlay_<hash>_<n>`，文本「签到」
* 已签到：同一元素额外挂 `_signBtnActive_<hash>_<n>`，文本「已签到」

class 里的 hash 段由微博前端构建工具生成，发版就变，所以用前缀包含匹配
`[class*='_signBtnOverlay_']`，另留文本精确匹配做兜底。

注意 `今日签到6.7万人 No.56` 那个 SPAN 是只读统计，不是按钮，
必须用 exact 精确匹配排除，否则会误点。

命令行
------
    python weibo_signin.py              正常跑：检测登录 -> 需要就登录 -> 签到
    python weibo_signin.py --dry-run    只检测，不点击
    python weibo_signin.py --login      强制进入登录流程（换机、登录态失效时用）
    python weibo_signin.py --setup-task 只注册计划任务，不签到
    python weibo_signin.py --headless   无界面运行（不弹窗口，日常定时任务用不到）

退出码
------
    0 成功或今日已签到   1 失败   2 脚本自身异常
"""

import argparse
import datetime
import json
import logging
import os
import subprocess
import sys
import time
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "profile")
LOG_DIR = os.path.join(BASE_DIR, "logs")
SHOT_DIR = os.path.join(BASE_DIR, "screenshots")
ALERT_DIR = os.path.join(BASE_DIR, "alerts")

# ---------------------------------------------------------------------------
# 配置区：换超话、改时间、调窗口，都改这里
# ---------------------------------------------------------------------------
CONFIG = {
    "super_name": "周深超话",
    "page_url": "https://weibo.com/p/100808cbec86fbcc1c453633f835c10c9db0ee",

    # 浏览器通道优先级：chrome > msedge > bundled（Playwright 自带 Chromium）
    # Edge 是 Windows 自带的，目标电脑不装任何东西通常也能用
    "channel_priority": ["chrome", "msedge", "bundled"],

    # 日常签到的窗口：带界面但挪到屏幕外，不打断你
    "offscreen_position": "-4000,-4000",
    "offscreen_size": "1440,900",

    # 首启登录时窗口要在屏幕内，用户才能操作
    "login_window_maximized": True,

    # 等用户完成登录的最长时间（秒）
    "login_timeout": 900,

    # 等页面/按钮出现的时间（毫秒）
    "nav_timeout_ms": 60000,
    "btn_wait_ms": 40000,
    "after_click_wait_s": 6,

    # 签到按钮定位：class 前缀包含匹配
    "sign_btn_selector": "[class*='_signBtnOverlay_']",

    # 计划任务
    "task_name": "WeiboSuperSignin_Daily",
    "task_time": "00:00",          # 每天几点签到
    "auto_register_task": True,    # 首次登录成功后自动注册计划任务

    # 失败时在桌面也留一份提醒文件
    "desktop_alert": True,
}

OK = "OK"
ALREADY = "ALREADY"
SKIP = "SKIP"
FAIL = "FAIL"

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------


def setup_logger():
    os.makedirs(LOG_DIR, exist_ok=True)
    today = datetime.date.today().strftime("%Y-%m-%d")
    log_file = os.path.join(LOG_DIR, "%s.log" % today)

    logger = logging.getLogger("weibo_signin")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    if sys.stdout is not None:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    return logger


log = setup_logger()


def desktop_dir():
    """找桌面目录。有的电脑桌面被 OneDrive 接管了。"""
    home = os.environ.get("USERPROFILE", "")
    for cand in (os.path.join(home, "Desktop"),
                 os.path.join(home, "OneDrive", "Desktop"),
                 os.path.join(home, "OneDrive", "桌面")):
        if os.path.isdir(cand):
            return cand
    return None


def write_alert(detail):
    """失败时写提醒：alerts\\ 一份，桌面一份。"""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    content = (
        "微博超话签到失败提醒\n"
        "====================\n"
        "时间：%s\n"
        "超话：%s\n"
        "地址：%s\n"
        "脚本目录：%s\n\n"
        "原因：\n%s\n\n"
        "排查建议：\n"
        "1. 先看 logs\\%s.log 里的本次记录\n"
        "2. 看 screenshots\\ 下本次截图\n"
        "3. 常见原因：\n"
        "   - 微博登录态过期 -> 双击「重新登录.bat」重新登录\n"
        "   - 微博超话页面改版 -> 需要重新定位签到按钮\n\n"
        "手动重跑：双击「启动签到.bat」，或运行\n"
        "  python weibo_signin.py\n"
    ) % (
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        CONFIG["super_name"], CONFIG["page_url"], BASE_DIR, detail,
        datetime.date.today().strftime("%Y-%m-%d"),
    )

    written = []
    for d in [ALERT_DIR] + ([desktop_dir()] if CONFIG.get("desktop_alert") else []):
        if not d:
            continue
        try:
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "微博超话签到失败_%s.txt" % stamp)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(content)
            written.append(p)
        except Exception as exc:
            log.warning("写提醒失败 %s: %s", d, exc)
    for p in written:
        log.info("已写提醒文件: %s", p)
    return written


# ---------------------------------------------------------------------------
# 浏览器通道选择
# ---------------------------------------------------------------------------
def pick_channel():
    """按优先级挑一个真能启动的浏览器通道。返回 (channel, 说明)。"""
    from playwright.sync_api import sync_playwright

    tried = []
    with sync_playwright() as p:
        for ch in CONFIG["channel_priority"]:
            try:
                if ch == "bundled":
                    b = p.chromium.launch(headless=True)
                else:
                    b = p.chromium.launch(channel=ch, headless=True)
                b.close()
                log.info("浏览器通道可用：%s", ch)
                return ch, "OK（试过 %s）" % (", ".join(tried) or "无")
            except Exception as exc:
                msg = str(exc).split("\n")[0][:110]
                tried.append("%s: %s" % (ch, msg))
                log.info("浏览器通道 %s 不可用：%s", ch, msg)
    return None, "；".join(tried)


def launch_ctx(p, channel, headless, for_login=False):
    """打开持久化上下文。for_login=True 时窗口放在屏幕内给用户操作。"""
    args = ["--disable-blink-features=AutomationControlled"]
    if not headless:
        if for_login:
            if CONFIG["login_window_maximized"]:
                args.append("--start-maximized")
        else:
            args.append("--window-size=%s" % CONFIG["offscreen_size"])
            args.append("--window-position=%s" % CONFIG["offscreen_position"])
    kwargs = dict(
        user_data_dir=PROFILE_DIR,
        headless=headless,
        no_viewport=True,
        args=args,
    )
    if channel and channel != "bundled":
        kwargs["channel"] = channel
    return p.chromium.launch_persistent_context(**kwargs)


# ---------------------------------------------------------------------------
# 登录态
# ---------------------------------------------------------------------------
def check_login(ctx, page):
    """判断是否真的已登录。返回 (bool, 依据)。

    注意：微博游客也会带 SUB cookie，只看它会把游客误判成已登录。
    所以用三个判据组合：$CONFIG.uid / SUBP cookie / 页面上有没有可见「登录」链接。
    """
    uid = ""
    try:
        uid = page.evaluate(
            "() => { try { return (window.$CONFIG && window.$CONFIG.uid) "
            "? String(window.$CONFIG.uid) : ''; } catch(e) { return ''; } }"
        ) or ""
    except Exception:
        uid = ""

    subp = False
    try:
        for ck in ctx.cookies("https://weibo.com"):
            if ck.get("name") == "SUBP" and ck.get("value"):
                subp = True
                break
    except Exception:
        pass

    login_link = False
    try:
        login_link = bool(page.evaluate(
            "() => { const es = [...document.querySelectorAll('a')]"
            ".filter(a => (a.innerText || '').trim() === '登录' "
            "&& a.getBoundingClientRect().width > 0); return es.length > 0; }"
        ))
    except Exception:
        pass

    logged = bool(uid) or subp or (not login_link)
    return logged, "uid=%r SUBP=%s 可见登录链接=%s" % (uid, subp, login_link)


def save_login_mark(uid):
    """在 profile 目录留个登录记录，便于排查（浏览器自己也会存 cookie）。"""
    try:
        p = os.path.join(PROFILE_DIR, "_login_state.json")
        data = {}
        if os.path.exists(p):
            try:
                data = json.load(open(p, encoding="utf-8"))
            except Exception:
                data = {}
        data["last_login"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data["uid"] = uid
        data["super"] = CONFIG["super_name"]
        data["machine"] = os.environ.get("COMPUTERNAME", "")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        log.info("已记录登录信息: %s", p)
    except Exception as exc:
        log.warning("写登录记录失败: %s", exc)


def quick_login_check(channel):
    """无界面快速探测登录态（不弹窗）。返回 (bool, 依据)。"""
    from playwright.sync_api import sync_playwright

    log.info("无界面预检登录态 ...")
    with sync_playwright() as p:
        ctx = launch_ctx(p, channel, headless=True)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(CONFIG["page_url"], wait_until="domcontentloaded",
                          timeout=CONFIG["nav_timeout_ms"])
            except Exception as exc:
                log.info("预检打开页面异常（继续判断）: %s", exc)
            time.sleep(4)
            return check_login(ctx, page)
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def manual_login(channel):
    """引导用户手动登录。返回 (是否成功, 说明)。"""
    from playwright.sync_api import sync_playwright

    log.info("=" * 58)
    log.info("需要登录微博")
    log.info("请在弹出的浏览器窗口里完成登录（扫码或账号密码都行）")
    log.info("登录成功后脚本会自动继续，最多等 %d 秒", CONFIG["login_timeout"])
    log.info("=" * 58)

    with sync_playwright() as p:
        ctx = launch_ctx(p, channel, headless=False, for_login=True)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(CONFIG["page_url"], wait_until="domcontentloaded",
                          timeout=CONFIG["nav_timeout_ms"])
            except Exception as exc:
                log.info("打开页面异常（不影响登录，可手动在窗口里操作）: %s", exc)

            time.sleep(5)
            logged, why = check_login(ctx, page)
            deadline = time.time() + CONFIG["login_timeout"]
            last = 0
            while not logged and time.time() < deadline:
                time.sleep(5)
                try:
                    logged, why = check_login(ctx, page)
                except Exception:
                    pass
                if time.time() - last > 30:
                    last = time.time()
                    log.info("等待登录中 ... (%s)", why)

            if not logged:
                return False, "等待 %d 秒仍未检测到登录，请重试「重新登录.bat」" % CONFIG["login_timeout"]

            log.info("登录成功！%s", why)
            save_login_mark(why)
            # 刷新一次，确认登录态在超话页面上确实生效
            try:
                page.goto(CONFIG["page_url"], wait_until="domcontentloaded",
                          timeout=CONFIG["nav_timeout_ms"])
                time.sleep(5)
            except Exception:
                pass
            return True, "登录成功"
        finally:
            try:
                ctx.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 元素定位与签到
# ---------------------------------------------------------------------------
def pick_visible(locator):
    try:
        n = locator.count()
    except Exception:
        return None
    for i in range(n):
        el = locator.nth(i)
        try:
            if el.is_visible():
                return el
        except Exception:
            continue
    return None


def find_sign_button(page):
    """定位签到按钮，返回 (locator, 依据)。找不到返回 (None, 说明)。"""
    el = pick_visible(page.locator(CONFIG["sign_btn_selector"]))
    if el is not None:
        return el, "class 前缀 %s" % CONFIG["sign_btn_selector"]

    # 文本兜底。必须 exact 精确匹配，否则会命中「今日签到6.7万人 No.56」
    for txt in ("签到", "已签到"):
        el = pick_visible(page.get_by_text(txt, exact=True))
        if el is not None:
            return el, "文本精确匹配 %r" % txt
    return None, "未找到签到按钮（class 前缀和文本兜底都没命中）"


def read_text(el):
    for getter in ("inner_text", "text_content"):
        try:
            return (getattr(el, getter)() or "").strip()
        except Exception:
            continue
    return ""


def collect_toasts(page):
    out = []
    try:
        out = page.evaluate(
            "() => { const es = document.querySelectorAll("
            "'[class*=toast],[class*=Toast],[class*=message],[class*=Message],"
            "[class*=tip],[class*=Tip]'); "
            "return [...es].map(e => (e.innerText || '').trim())"
            ".filter(t => t && t.length < 60).slice(0, 10); }"
        ) or []
    except Exception:
        pass
    return out


def do_signin(channel, dry_run=False, headless=False):
    """执行签到。假定登录态已经确认。"""
    from playwright.sync_api import sync_playwright
    from playwright.sync_api import TimeoutError as PWTimeout

    os.makedirs(SHOT_DIR, exist_ok=True)
    os.makedirs(PROFILE_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    shot_before = os.path.join(SHOT_DIR, "%s_before.png" % stamp)
    shot_after = os.path.join(SHOT_DIR, "%s_after.png" % stamp)

    with sync_playwright() as p:
        ctx = launch_ctx(p, channel, headless=headless, for_login=False)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            log.info("打开超话页面: %s", CONFIG["page_url"])
            try:
                page.goto(CONFIG["page_url"], wait_until="domcontentloaded",
                          timeout=CONFIG["nav_timeout_ms"])
            except PWTimeout:
                raise RuntimeError("打开超话页面超时")

            try:
                page.wait_for_selector(CONFIG["sign_btn_selector"],
                                       timeout=CONFIG["btn_wait_ms"])
            except PWTimeout:
                log.info("等待签到按钮出现超时，继续尝试兜底定位")
            time.sleep(3)

            btn, how = find_sign_button(page)
            if btn is None:
                logged, info = check_login(ctx, page)
                try:
                    page.screenshot(path=shot_before)
                    log.info("截图: %s", shot_before)
                except Exception:
                    pass
                if not logged:
                    return {"status": SKIP, "detail":
                            "未检测到登录态（%s），需要重新登录" % info}
                return {"status": SKIP, "detail":
                        "%s，疑似超话页面改版或渲染未完成" % how}

            log.info("定位到签到按钮（依据：%s）", how)
            text_before = read_text(btn)
            log.info("点击前按钮文本=%r", text_before)

            if "已签" in text_before:
                try:
                    page.screenshot(path=shot_before)
                except Exception:
                    pass
                return {"status": ALREADY,
                        "detail": "今日已签到（按钮显示「%s」），无需操作" % text_before}

            if "签到" not in text_before:
                return {"status": FAIL,
                        "detail": "按钮文本异常 %r，既不是「签到」也不是「已签到」，"
                                  "为避免误点未执行点击" % text_before}

            try:
                page.screenshot(path=shot_before)
                log.info("点击前截图: %s", shot_before)
            except Exception:
                pass

            if dry_run:
                return {"status": SKIP,
                        "detail": "[dry-run] 按钮可点击（文本「%s」），未实际点击" % text_before}

            clicked = False
            try:
                btn.click(timeout=15000)
                clicked = True
                log.info("已通过 Playwright click 点击签到按钮")
            except Exception as exc:
                log.warning("Playwright click 失败（%s），改用坐标点击", exc)
            if not clicked:
                try:
                    box = btn.bounding_box()
                    if box:
                        page.mouse.click(box["x"] + box["width"] / 2,
                                         box["y"] + box["height"] / 2)
                        clicked = True
                        log.info("已通过鼠标坐标点击")
                except Exception as exc:
                    log.warning("坐标点击也失败: %s", exc)
            if not clicked:
                return {"status": FAIL, "detail": "签到按钮点击失败"}

            time.sleep(CONFIG["after_click_wait_s"])
            for t in collect_toasts(page):
                log.info("页面提示文案: %r", t)
            try:
                page.screenshot(path=shot_after)
                log.info("点击后截图: %s", shot_after)
            except Exception:
                pass

            btn2, how2 = find_sign_button(page)
            if btn2 is None:
                return {"status": SKIP,
                        "detail": "点击后签到按钮消失（依据 %s），无法确认结果，"
                                  "请查截图 %s" % (how2, shot_after)}

            text_after = read_text(btn2)
            log.info("点击后按钮文本=%r", text_after)
            if "已签" in text_after:
                return {"status": OK,
                        "detail": "签到成功，按钮已由「%s」变为「%s」"
                                  % (text_before, text_after)}
            return {"status": FAIL,
                    "detail": "点击后按钮文本仍为「%s」，状态未变化，签到可能失败"
                              % text_after}
        finally:
            try:
                ctx.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 计划任务注册（用 schtasks + XML，能设置"错过补跑"）
# ---------------------------------------------------------------------------
TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>微博超话每日签到（%s）</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>%sT%s:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>%s</Command>
      <Arguments>"%s"</Arguments>
      <WorkingDirectory>%s</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def task_exists():
    try:
        r = subprocess.run(
            ["schtasks", "/Query", "/TN", CONFIG["task_name"]],
            capture_output=True, text=True, timeout=30,
            encoding="gbk", errors="replace")
        return r.returncode == 0
    except Exception:
        return False


def register_task():
    """注册每天定时执行的计划任务。返回 (是否成功, 说明)。"""
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable

    today = datetime.date.today().strftime("%Y-%m-%d")
    xml = TASK_XML % (CONFIG["super_name"], today, CONFIG["task_time"],
                      pythonw,
                      os.path.join(BASE_DIR, "weibo_signin.py"),
                      BASE_DIR)

    xml_path = os.path.join(BASE_DIR, "tools", "_task.xml")
    os.makedirs(os.path.dirname(xml_path), exist_ok=True)
    try:
        # schtasks /XML 要求 UTF-16 编码的文件
        with open(xml_path, "w", encoding="utf-16") as fh:
            fh.write(xml)
    except Exception as exc:
        return False, "写任务 XML 失败: %s" % exc

    try:
        r = subprocess.run(
            ["schtasks", "/Create", "/TN", CONFIG["task_name"],
             "/XML", xml_path, "/F"],
            capture_output=True, text=True, timeout=60,
            encoding="gbk", errors="replace")
    except Exception as exc:
        return False, "调用 schtasks 失败: %s" % exc

    out = ((r.stdout or "") + (r.stderr or "")).strip()
    log.info("schtasks 返回码=%s 输出=%s", r.returncode, out)
    if r.returncode != 0:
        return False, "注册失败（返回码 %s）：%s" % (r.returncode, out[:300])
    return True, "已注册计划任务 %s，每天 %s 执行" % (CONFIG["task_name"], CONFIG["task_time"])


def start_task_now():
    try:
        subprocess.run(["schtasks", "/Run", "/TN", CONFIG["task_name"]],
                       capture_output=True, text=True, timeout=30,
                       encoding="gbk", errors="replace")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="微博超话每日签到")
    ap.add_argument("--dry-run", action="store_true", help="只检测不点击")
    ap.add_argument("--login", action="store_true", help="强制进入登录流程")
    ap.add_argument("--setup-task", action="store_true", help="只注册计划任务")
    ap.add_argument("--headless", action="store_true", help="无界面运行")
    ap.add_argument("--no-desktop-alert", action="store_true", help="失败时不在桌面留提醒")
    args = ap.parse_args()

    if args.no_desktop_alert:
        CONFIG["desktop_alert"] = False

    log.info("=" * 58)
    log.info("微博超话签到开始 | 目标：%s", CONFIG["super_name"])
    log.info("脚本目录：%s", BASE_DIR)

    if args.setup_task:
        ok, msg = register_task()
        log.info("注册计划任务：%s", msg)
        return 0 if ok else 1

    # 1. 挑浏览器
    channel, why = pick_channel()
    if channel is None:
        log.error("没有可用的浏览器通道：%s", why)
        write_alert("没有可用的浏览器。\n%s\n\n处理：运行 setup_env.py 安装浏览器。" % why)
        return 1

    # 2. 查登录态（--login 时跳过预检，直接进登录流程）
    need_login = args.login
    if not args.login:
        try:
            logged, why = quick_login_check(channel)
            log.info("登录预检：%s | %s", logged, why)
            need_login = not logged
        except Exception as exc:
            log.warning("登录预检异常（按未登录处理）: %s", exc)
            need_login = True

    # 3. 需要就引导登录
    if need_login:
        ok, msg = manual_login(channel)
        if not ok:
            log.error("登录未完成：%s", msg)
            write_alert(msg)
            return 1
        # 首次登录成功 -> 补注册计划任务（若还没有）
        if CONFIG["auto_register_task"] and not task_exists():
            ok2, msg2 = register_task()
            log.info("自动注册计划任务：%s", msg2)
            if ok2:
                log.info("以后每天 %s 会自动签到，不用再管", CONFIG["task_time"])

    # 4. 签到
    log.info("-" * 58)
    result = do_signin(channel, dry_run=args.dry_run, headless=args.headless)
    log.info("结果 | %s | %s", result["status"], result["detail"])

    if result["status"] == FAIL:
        write_alert(result["detail"])
    log.info("=" * 58)
    return 0 if result["status"] in (OK, ALREADY, SKIP) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.info("被用户中断")
        sys.exit(1)
    except Exception:
        log.critical("脚本未捕获异常:\n%s", traceback.format_exc())
        sys.exit(2)
