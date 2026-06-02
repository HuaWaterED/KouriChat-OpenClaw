"""
KouriChat main module — 路 D 改造版。

改造后 KouriChat 不再直接收发 QQ / 微信消息：
- QQ 消息收发由 OpenClaw 自带的 qqbot 通道负责 (http://127.0.0.1:18789)
- KouriChat 仅在启动时把 prompt / 人设注入到 OpenClaw agent
- 主动调用 LLM 走 OpenClawBridge (subprocess openclaw agent --local)
- KouriChat 主进程 = prompt 注入器 + 主动消息触发器 + 健康检查服务

微信 (wxauto) 渠道已完全删除。详见 PLAN.md。
"""

import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

# 确保 src 在 path 上
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "src"))

from colorama import init as colorama_init, Style
from src.utils.console import print_status
from src.openclaw_bridge import OpenClawBridge

colorama_init()

# 全局 logger
logger: logging.Logger | None = None
bridge: OpenClawBridge | None = None
stop_event = threading.Event()


def setup_logging() -> None:
    global logger
    log_dir = root_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "bot.log"

    # 清空旧 handler
    for h in logging.root.handlers[:]:
        logging.root.removeHandler(h)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    logger = logging.getLogger("kourichat")


def log(msg: str) -> None:
    if logger:
        logger.info(msg)
    print_status(msg, "info", "KOURI")


def main() -> None:
    """主入口。路 D 改造：启动 bridge，注入 prompt，提供主动消息接口。

    工作流：
    1. 初始化 logging
    2. 读 KouriChat config (data/config/config.json)
    3. 启动 OpenClawBridge，注入 prompt 到 OpenClaw agent
    4. health check OpenClaw gateway
    5. 起 HTTP health endpoint (可选)
    6. 后台等待 stop_event (SIGTERM/SIGINT 优雅退出)
    """
    global bridge

    print_status("启动 KouriChat (路 D / OpenClaw 模式)...", "info", "LAUNCH")
    print("=" * 50)

    # === 1. logging ===
    setup_logging()
    log("KouriChat 路 D 模式启动")

    # === 2. config ===
    try:
        from data.config import config
        oc_cfg = config.openclaw
        log(f"OpenClaw 配置: agent_id={oc_cfg.agent_id} use_local={oc_cfg.use_local} sync_on_start={oc_cfg.sync_prompts_on_start}")
    except Exception as e:
        log(f"读 config 失败: {e}")
        oc_cfg = None

    # === 3. bridge + prompt 注入 ===
    try:
        bridge = OpenClawBridge(
            gateway_token=os.environ.get("OPENCLAW_GATEWAY_TOKEN"),
            agent_id=(oc_cfg.agent_id if oc_cfg else "main"),
        )
        log(f"OpenClawBridge 初始化: CLI={bridge.openclaw_bin}")
    except Exception as e:
        log(f"OpenClawBridge 初始化失败: {e}")
        sys.exit(1)

    if not oc_cfg or oc_cfg.sync_prompts_on_start:
        try:
            sync_result = bridge.sync_prompts()
            log(f"Prompt 注入完成: SOUL={sync_result['soul_size']}B AGENTS.md={sync_result['agents_md_size']}B bootstrap_removed={sync_result['bootstrap_removed']}")
        except Exception as e:
            log(f"Prompt 注入失败（继续运行）: {e}")

    # === 4. health check ===
    health = bridge.health_check()
    if not health.get("gateway"):
        log(f"⚠️  OpenClaw gateway 不可用: {health.get('details', {})}")
        log("请确认 `openclaw gateway run` 已在跑（端口 18789）")
    else:
        log(f"✅ OpenClaw gateway ok ({health.get('version')})")

    # === 5. HTTP health endpoint (可选) ===
    http_port = (oc_cfg.http_health_port if oc_cfg else 0) or 0
    if http_port > 0:
        _start_health_server(http_port, ask_timeout=(oc_cfg.ask_timeout if oc_cfg else 60))

    print("=" * 50)
    log("KouriChat 已就绪。后台等待。")
    log("  - QQ 消息由 OpenClaw qqbot 通道自动处理")
    log("  - 主动调 LLM: bridge.ask_agent(message)")
    log("  - 停止: Ctrl+C / SIGTERM")

    # === 6. signal handling + 等待退出 ===
    def _on_signal(signum, frame):
        log(f"收到信号 {signum}，准备退出")
        stop_event.set()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    try:
        while not stop_event.is_set():
            stop_event.wait(timeout=1.0)
    except KeyboardInterrupt:
        log("KeyboardInterrupt")
    finally:
        log("KouriChat 退出")


def _start_health_server(port: int, ask_timeout: int) -> None:
    """起一个最小 Flask HTTP server，暴露 /health 端点。"""
    try:
        from flask import Flask, jsonify
    except ImportError:
        log("Flask 未安装，跳过 HTTP health endpoint")
        return

    app = Flask("kourichat-health")

    @app.route("/health")
    def health():
        if bridge is None:
            return jsonify({"status": "no_bridge"}), 503
        h = bridge.health_check()
        status = "ok" if h.get("gateway") else "degraded"
        return jsonify({"status": status, **h})

    @app.route("/ask", methods=["POST"])
    def ask():
        if bridge is None:
            return jsonify({"error": "no_bridge"}), 503
        from flask import request
        data = request.get_json(force=True, silent=True) or {}
        msg = data.get("message") or ""
        if not msg:
            return jsonify({"error": "missing message"}), 400
        reply = bridge.ask_agent(msg, timeout=ask_timeout)
        return jsonify({"reply": reply})

    t = threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False), daemon=True)
    t.start()
    log(f"HTTP health endpoint: http://127.0.0.1:{port}/health, /ask (POST)")


if __name__ == "__main__":
    main()
