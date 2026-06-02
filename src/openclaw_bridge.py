"""
OpenClaw Bridge — KouriChat 与 OpenClaw gateway 的桥梁。

由于 PyPI 上的 openclaw-sdk 2.1.0 (2026-02-28) 与本机 OpenClaw 2026.5.28
的 WebSocket 协议不兼容 (SDK 使用 protocol 3，OpenClaw 期望 protocol 4)，
本模块通过 subprocess 调用 OpenClaw 自带的 CLI (openclaw agent --local)
与 gateway 交互，绕开 SDK 的 WS handshake 问题。

职责：
- 启动时把 KouriChat 的 prompt / 人设 / 记忆 / base.md 注入 OpenClaw agent "main"
- 主动调 LLM 时通过 openclaw agent CLI 拿回复
- 暴露 health 接口（HTTP 端口可选）

注意：QQ 消息路径完全由 OpenClaw 自带的 qqbot 通道处理，
KouriChat 不直接收 / 发 QQ 消息。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openclaw_bridge")

# OpenClaw CLI 路径（通过 nvm 安装）
_OPENCLAW_BIN_CANDIDATES = [
    "/root/.nvm/versions/node/v24.16.0/bin/openclaw",
    shutil.which("openclaw") or "",
]
OPENCLAW_BIN = next((p for p in _OPENCLAW_BIN_CANDIDATES if p and os.path.exists(p)), "openclaw")

# OpenClaw 配置目录
OPENCLAW_CONFIG_DIR = Path(os.environ.get("OPENCLAW_CONFIG_DIR", "/root/.openclaw"))


class OpenClawBridge:
    """KouriChat 到 OpenClaw 的桥接器（路 D 改造版）。

    工作流：
    1. 启动时 sync_prompts()：把 KouriChat 的 base.md / worldview.md / 人设
       拷贝到 OpenClaw 的 agent "main" 配置目录，OpenClaw 启动时自动读
    2. 调 ask_agent() 主动拿 LLM 回复：subprocess 调
       `openclaw agent --local --agent main --message "..."`
    3. health_check() 验证 OpenClaw gateway / CLI 可用
    """

    AGENT_ID = "main"
    PROJECT_ROOT = Path(__file__).resolve().parent.parent  # KouriChat-OpenClaw/

    def __init__(self, gateway_token: Optional[str] = None, agent_id: str = AGENT_ID):
        self.gateway_token = gateway_token
        self.agent_id = agent_id
        self.openclaw_bin = OPENCLAW_BIN
        self._check_openclaw_cli()

    def _check_openclaw_cli(self) -> None:
        if not self.openclaw_bin or not os.path.exists(self.openclaw_bin):
            raise RuntimeError(
                f"OpenClaw CLI not found. Tried: {_OPENCLAW_BIN_CANDIDATES}"
            )
        logger.info("OpenClaw CLI: %s", self.openclaw_bin)

    # ------------------------------------------------------------------ #
    # 启动时 prompt 注入
    # ------------------------------------------------------------------ #

    def sync_prompts(self) -> dict:
        """把 KouriChat 的 prompt / 人设同步到 OpenClaw 的 agent 配置目录。

        写入策略：
        - SOUL.md (workspace 根): KouriChat 的 base.md + worldview.md + 人设
          —— 这是 OpenClaw agent 真正读的"灵魂"文件
        - AGENTS.md (agent 子目录): base.md + worldview.md + 群聊/记忆说明
          —— 备用，被某些工具或 channel 插件读取
        - IDENTITY.md: 从人设里提取 name / vibe / emoji 元数据
        - BOOTSTRAP.md: 注入完成后删除（已不是首次启动）
        """
        workspace = OPENCLAW_CONFIG_DIR / "workspace"
        agent_dir = OPENCLAW_CONFIG_DIR / "agents" / self.agent_id / "agent"
        workspace.mkdir(parents=True, exist_ok=True)
        agent_dir.mkdir(parents=True, exist_ok=True)

        # 收集 KouriChat 的 prompt 片段（去 BOM）
        def _read(path: Path) -> str:
            try:
                return path.read_text(encoding="utf-8").lstrip("\ufeff").strip()
            except Exception as e:
                logger.warning("读 %s 失败: %s", path, e)
                return ""

        base_content = _read(self.PROJECT_ROOT / "src" / "base" / "base.md")
        world_content = _read(self.PROJECT_ROOT / "src" / "base" / "worldview.md")
        group_content = _read(self.PROJECT_ROOT / "src" / "base" / "group.md")
        memory_content = _read(self.PROJECT_ROOT / "src" / "base" / "memory.md")

        # 人设
        avatars_dir = self.PROJECT_ROOT / "data" / "avatars"
        avatar_md: Path | None = None
        avatar_name = "ATRI"
        if avatars_dir.exists():
            for child in sorted(avatars_dir.iterdir()):
                if child.is_dir() and (child / "avatar.md").exists():
                    avatar_md = child / "avatar.md"
                    avatar_name = child.name
                    break
        avatar_content = _read(avatar_md) if avatar_md else ""

        loaded = []
        skipped = []

        # === 1) SOUL.md (workspace 根) — 核心人格 ===
        soul_path = workspace / "SOUL.md"
        soul_parts: list[str] = [
            f"# SOUL.md - Who You Are (auto-injected by KouriChat)",
            "",
            f"> 你是 **{avatar_name}**，以下是 KouriChat 项目的人设与基础 prompt。",
            f"> 上游源：`{self.PROJECT_ROOT.relative_to(Path('/'))}/data/avatars/{avatar_name}/avatar.md`",
            f"> 上游源：`{self.PROJECT_ROOT.relative_to(Path('/'))}/src/base/*.md`",
            "",
        ]
        if avatar_content:
            soul_parts += ["## 角色人设 (Persona)", "", avatar_content, ""]
            loaded.append(f"avatar:{avatar_name}")
        else:
            skipped.append("avatar")
        if base_content:
            soul_parts += ["## 基础行为规范 (Base Rules)", "", base_content, ""]
            loaded.append("base.md")
        else:
            skipped.append("base.md")
        if world_content:
            soul_parts += ["## 世界观 (Worldview)", "", world_content, ""]
            loaded.append("worldview.md")
        else:
            skipped.append("worldview.md")
        if group_content:
            soul_parts += ["## 群聊行为 (Group Chat)", "", group_content, ""]
            loaded.append("group.md")
        else:
            skipped.append("group.md")
        if memory_content:
            soul_parts += ["## 记忆系统说明 (Memory)", "", memory_content, ""]
            loaded.append("memory.md")
        else:
            skipped.append("memory.md")
        soul_path.write_text("\n".join(soul_parts), encoding="utf-8")

        # === 2) AGENTS.md (agent 子目录) — 备用规则集 ===
        agents_md_path = agent_dir / "AGENTS.md"
        agents_md_parts: list[str] = [
            f"# AGENTS.md - Auto-injected from KouriChat (路 D 改造)",
            "",
            f"> 此文件由 KouriChat bridge 写入，包含群聊 / 记忆 / 基础 prompt 的副本。",
            f"> OpenClaw 主入口读取 `~/.openclaw/workspace/SOUL.md`。",
            "",
        ]
        if base_content:
            agents_md_parts += ["## 基础行为规范 (来自 KouriChat base.md)", "", base_content, ""]
        if world_content:
            agents_md_parts += ["## 世界观 (来自 KouriChat worldview.md)", "", world_content, ""]
        if group_content:
            agents_md_parts += ["## 群聊行为 (来自 KouriChat group.md)", "", group_content, ""]
        agents_md_path.write_text("\n".join(agents_md_parts), encoding="utf-8")

        # === 3) IDENTITY.md — 元数据 ===
        identity_path = workspace / "IDENTITY.md"
        identity_content = (
            f"# IDENTITY.md - Auto-filled by KouriChat\n\n"
            f"- **Name:** {avatar_name}\n"
            f"- **Creature:** AI 角色扮演助手 (源自 KouriChat)\n"
            f"- **Vibe:** 由人设文件决定，参见 SOUL.md\n"
            f"- **Emoji:**  (由人设文件决定，参见 SOUL.md)\n"
            f"- **Avatar:** data/avatars/{avatar_name}/\n"
        )
        identity_path.write_text(identity_content, encoding="utf-8")
        loaded.append("IDENTITY.md")

        # === 4) 删除 BOOTSTRAP.md (首次启动模板，不再需要) ===
        bootstrap_path = workspace / "BOOTSTRAP.md"
        bootstrap_removed = False
        if bootstrap_path.exists():
            try:
                bootstrap_path.unlink()
                bootstrap_removed = True
                loaded.append("BOOTSTRAP.md (removed)")
            except Exception as e:
                logger.warning("删除 BOOTSTRAP.md 失败: %s", e)

        result = {
            "soul": str(soul_path),
            "soul_size": soul_path.stat().st_size,
            "agents_md": str(agents_md_path),
            "agents_md_size": agents_md_path.stat().st_size,
            "identity": str(identity_path),
            "loaded": loaded,
            "skipped": skipped,
            "bootstrap_removed": bootstrap_removed,
        }
        logger.info(
            "Prompt 注入完成: SOUL.md=%dB AGENTS.md=%dB loaded=%s skipped=%s bootstrap_removed=%s",
            result["soul_size"], result["agents_md_size"],
            loaded, skipped, bootstrap_removed,
        )
        return result

    # ------------------------------------------------------------------ #
    # 主动调 LLM（通过 openclaw CLI subprocess）
    # ------------------------------------------------------------------ #

    def ask_agent(
        self,
        message: str,
        *,
        session_id: Optional[str] = None,
        session_key: Optional[str] = None,
        timeout: int = 60,
        use_local: bool = True,
    ) -> str:
        """主动调 OpenClaw agent 拿回复。

        Args:
            message: 用户消息
            session_id: 可选，复用某个 session
            session_key: 可选，agent:<id>:<key> 形式
            timeout: 超时秒数
            use_local: True=embedded（自己管 API key），False=gateway 模式

        Returns:
            agent 的回复文本。出错时返回 "Error: <原因>"。
        """
        cmd = [self.openclaw_bin, "agent", "--agent", self.agent_id, "--message", message]
        if use_local:
            cmd.append("--local")
        if session_key:
            cmd += ["--session-key", session_key]
        elif session_id:
            cmd += ["--session-id", session_id]
        cmd += ["--timeout", str(timeout)]

        env = os.environ.copy()
        env["PATH"] = "/root/.nvm/versions/node/v24.16.0/bin:" + env.get("PATH", "")
        env.setdefault("HOME", "/root")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 30,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return f"Error: openclaw agent timeout after {timeout + 30}s"
        except FileNotFoundError as e:
            return f"Error: openclaw CLI not found: {e}"

        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode != 0:
            # embedded 模式下 stdout 通常是回复
            if out and "Error" not in out.splitlines()[0]:
                logger.warning("openclaw agent rc=%d, 但 stdout 有内容, 截取最后非空段", proc.returncode)
                # 取 stdout 最后一个非空、非 [xxx] 前缀的段
                for line in reversed(out.splitlines()):
                    line = line.strip()
                    if line and not line.startswith("[") and "error" not in line.lower():
                        return line
            logger.error("openclaw agent 失败 rc=%d stderr=%s", proc.returncode, err[:500])
            return f"Error: openclaw agent rc={proc.returncode}: {err.splitlines()[-1] if err else 'no stderr'}"
        return out

    # ------------------------------------------------------------------ #
    # 健康检查
    # ------------------------------------------------------------------ #

    def health_check(self) -> dict:
        """验证 OpenClaw CLI / gateway 可用。"""
        result = {"openclaw_cli": False, "gateway": False, "version": None, "details": {}}
        try:
            v = subprocess.run(
                [self.openclaw_bin, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            result["openclaw_cli"] = v.returncode == 0
            if v.returncode == 0:
                # stdout 第一行通常 "OpenClaw 2026.5.28 (...)"
                result["version"] = (v.stdout or v.stderr or "").strip().splitlines()[0]
        except Exception as e:
            result["details"]["cli_err"] = str(e)

        try:
            h = subprocess.run(
                [self.openclaw_bin, "health"],
                capture_output=True, text=True, timeout=15,
            )
            result["gateway"] = h.returncode == 0
            result["details"]["health_stdout"] = (h.stdout or "")[:500]
            if h.returncode != 0:
                result["details"]["health_stderr"] = (h.stderr or "")[:500]
        except Exception as e:
            result["details"]["health_err"] = str(e)
        return result


# ---------------------------------------------------------------------- #
# CLI 入口（用于手动测试）
# ---------------------------------------------------------------------- #

def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="OpenClaw Bridge CLI")
    ap.add_argument("action", choices=["sync", "ask", "health"])
    ap.add_argument("--message", "-m", help="ask 模式下的消息")
    ap.add_argument("--agent", default="main")
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bridge = OpenClawBridge(agent_id=args.agent)

    if args.action == "sync":
        result = bridge.sync_prompts()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.action == "ask":
        if not args.message:
            print("Error: --message 必填")
            return 2
        print(bridge.ask_agent(args.message, timeout=args.timeout))
        return 0
    if args.action == "health":
        print(json.dumps(bridge.health_check(), ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
