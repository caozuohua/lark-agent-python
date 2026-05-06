"""
Lark Bot + Vertex AI Agent - v4.2
新增：GitHub 集成 / 动态工具系统 / 博客管理
新增：支持模型设置
优化：run_shell预处理
"""

import os
import json
import time
import logging
import subprocess
from collections import defaultdict

import lark_oapi as lark
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
from google.oauth2 import service_account
from sqlitedict import SqliteDict
import vertexai
from vertexai.generative_models import (
    GenerativeModel, Tool, FunctionDeclaration, Part, Content
)

# ─── 日志 ────────────────────────────────────────────────────────────[...]
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ─── 配置 ────────────────────────────────────────────────────────────[...]
LARK_APP_ID       = os.environ["LARK_APP_ID"]
LARK_APP_SECRET   = os.environ["LARK_APP_SECRET"]
GCP_PROJECT_ID    = os.environ["GCP_PROJECT_ID"]
GCP_LOCATION      = os.environ.get("GCP_LOCATION", "us-central1")
GEMINI_MODEL      = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
SYSTEM_PROMPT     = os.environ.get("SYSTEM_PROMPT", "你是一个专业的 AI 助手，可以帮助管理博客、执行代码和管理 GitHub 项目。")
MAX_HISTORY_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "20"))
DB_PATH           = os.environ.get("DB_PATH", "/opt/lark-agent/agent.db")
CREDENTIALS_FILE  = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "/opt/lark-agent/credentials.json")
ADMIN_USERS       = set(filter(None, os.environ.get("ADMIN_USERS", "").split(",")))
BLOG_DIR          = os.environ.get("BLOG_DIR", "/var/www/blog")
GITHUB_TOKEN      = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USER       = os.environ.get("GITHUB_USER", "")

# ─── 持久化存储 ─────────────────────────────────────────────────────────[...]
history_db    = SqliteDict(DB_PATH, tablename="history",     autocommit=True)
preference_db = SqliteDict(DB_PATH, tablename="preferences", autocommit=True)
memory_db     = SqliteDict(DB_PATH, tablename="memory",      autocommit=True)
evolution_db  = SqliteDict(DB_PATH, tablename="evolution",   autocommit=True)
tools_db      = SqliteDict(DB_PATH, tablename="custom_tools", autocommit=True)  # 动态工具库

# ─── 消息去重 ──────────────────────────────────────────────────────────[...]
processed_message_ids: set = set()

# ─── 运行时可变状态 ───────────────────────────────────────────────────────[...]
_current_system_prompt = SYSTEM_PROMPT

# ─── Lark 客户端 ────────────────────────────────────────────────────────[...]
lark_client = lark.Client.builder() \
    .app_id(LARK_APP_ID) \
    .app_secret(LARK_APP_SECRET) \
    .domain(lark.LARK_DOMAIN) \
    .build()


# ════════════════════════════════════════════════════════════════[...]
# Shell 执行（基础能力）
# ════════════════════════════════════════════════════════════════[...]

def run_shell(command: str, timeout: int = 30, cwd: str = None) -> str:
    """执行 shell 命令，返回结果"""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True,
            text=True, timeout=timeout, cwd=cwd
        )
        output = (result.stdout + result.stderr).strip()
        output = output[:3000]
        return f"退出码: {result.returncode}\n{output}" if output else f"退出码: {result.returncode}"
    except subprocess.TimeoutExpired:
        return f"❌ 命令超时（{timeout}s）"
    except Exception as e:
        return f"❌ 执行失败: {e}"


# ════════════════════════════════════════════════════════════════[...]
# 工具定义
# ════════════════════════════════════════════════════════════════[...]

def build_tools() -> Tool:
    """构建工具列表（含动态工具）"""

    declarations = [

        # ── 系统工具 ────────────────────────────────────────────────────────[...]
        FunctionDeclaration(
            name="run_shell",
            description="在 VPS 上执行 shell 命令。可用于查看系统状态、管理文件、运行脚本等。仅限管理员。",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd":     {"type": "string", "description": "工作目录，可选"},
                    "timeout": {"type": "integer", "description": "超时秒数，默认30"}
                },
                "required": ["command"]
            }
        ),

        # ── 博客工具 ────────────────────────────────────────────────────────[...]
        FunctionDeclaration(
            name="blog_write",
            description="创建或更新博客文章。自动生成 Hugo 格式的 Markdown 文件。",
            parameters={
                "type": "object",
                "properties": {
                    "title":   {"type": "string", "description": "文章标题"},
                    "content": {"type": "string", "description": "文章正文（Markdown）"},
                    "tags":    {"type": "string", "description": "标签，逗号分隔"},
                    "draft":   {"type": "boolean", "description": "是否草稿，默认false"}
                },
                "required": ["title", "content"]
            }
        ),

        FunctionDeclaration(
            name="blog_list",
            description="列出所有博客文章及其状态。",
            parameters={"type": "object", "properties": {}}
        ),

        FunctionDeclaration(
            name="blog_publish",
            description="构建并发布博客（运行 hugo build）。",
            parameters={
                "type": "object",
                "properties": {
                    "push_github": {"type": "boolean", "description": "是否同时推送到 GitHub Pages，默认false"}
                }
            }
        ),

        FunctionDeclaration(
            name="blog_delete",
            description="删除指定博客文章。",
            parameters={
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "文章文件名"}
                },
                "required": ["filename"]
            }
        ),

        # ── GitHub 工具 ──────────────────────────────────────────────────────
        FunctionDeclaration(
            name="github_repo_list",
            description="列出 GitHub 账号下的仓库。",
            parameters={
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "all/public/private，默认all"}
                }
            }
        ),

        FunctionDeclaration(
            name="github_file_write",
            description="在 GitHub 仓库中创建或更新文件。",
            parameters={
                "type": "object",
                "properties": {
                    "repo":    {"type": "string", "description": "仓库名，如 myblog"},
                    "path":    {"type": "string", "description": "文件路径，如 content/posts/hello.md"},
                    "content": {"type": "string", "description": "文件内容"},
                    "message": {"type": "string", "description": "commit 消息"}
                },
                "required": ["repo", "path", "content", "message"]
            }
        ),

        FunctionDeclaration(
            name="github_repo_create",
            description="在 GitHub 上创建新仓库。",
            parameters={
                "type": "object",
                "properties": {
                    "name":        {"type": "string"},
                    "description": {"type": "string"},
                    "private":     {"type": "boolean", "description": "是否私有，默认false"}
                },
                "required": ["name"]
            }
        ),

        # ── 动态工具管理 ──────────────────────────────────────────────────────
        FunctionDeclaration(
            name="tool_create",
            description="创建新工具：将一段 shell 脚本或 Python 代码注册为可调用工具，实现自我扩展。仅限管理员。",
            parameters={
                "type": "object",
                "properties": {
                    "name":        {"type": "string", "description": "工具名称（英文，下划线连接）"},
                    "description": {"type": "string", "description": "工具功能描述"},
                    "script":      {"type": "string", "description": "工具脚本内容（bash 或 python3）"},
                    "lang":        {"type": "string", "description": "脚本语言: bash 或 python3"},
                    "params_desc": {"type": "string", "description": "参数说明，JSON 字符串"}
                },
                "required": ["name", "description", "script", "lang"]
            }
        ),

        FunctionDeclaration(
            name="tool_list",
            description="列出所有已注册的自定义工具。",
            parameters={"type": "object", "properties": {}}
        ),

        FunctionDeclaration(
            name="tool_run",
            description="运行一个已注册的自定义工具。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "工具名称"},
                    "args": {"type": "string", "description": "传递给工具的参数（JSON 字符串）"}
                },
                "required": ["name"]
            }
        ),

        FunctionDeclaration(
            name="tool_delete",
            description="删除一个已注册的自定义工具。仅限管理员。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"}
                },
                "required": ["name"]
            }
        ),

        # ── 记忆工具 ────────────────────────────────────────────────────────[...]
        FunctionDeclaration(
            name="remember",
            description="将重要信息存入长期记忆。",
            parameters={
                "type": "object",
                "properties": {
                    "key":   {"type": "string"},
                    "value": {"type": "string"}
                },
                "required": ["key", "value"]
            }
        ),

        FunctionDeclaration(
            name="recall",
            description="从长期记忆中检索信息。",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string"}
                },
                "required": ["key"]
            }
        ),

        FunctionDeclaration(
            name="update_system_prompt",
            description="更新自己的系统提示词（自我进化）。仅限管理员。",
            parameters={
                "type": "object",
                "properties": {
                    "new_prompt": {"type": "string"},
                    "reason":     {"type": "string"}
                },
                "required": ["new_prompt", "reason"]
            }
        ),

        FunctionDeclaration(
            name="get_agent_status",
            description="获取 Agent 当前状态。",
            parameters={"type": "object", "properties": {}}
        ),
    ]

    return Tool(function_declarations=declarations)


# ════════════════════════════════════════════════════════════════[...]
# 工具执行
# ═══════════════���════════════════════════════════════════════════[...]

def execute_tool(tool_name: str, args: dict, user_id: str) -> str:
    global _current_system_prompt

    is_admin = not ADMIN_USERS or user_id in ADMIN_USERS

    # ── run_shell ────────────────────────────────────────────────────────[...]
    if tool_name == "run_shell":
        if not is_admin:
            return "❌ 权限不足"
        cmd = args.get("command", "")
        cwd = args.get("cwd", None)
        timeout = args.get("timeout", 30)

        # 自动为需要权限的命令加 sudo
        SUDO_PREFIXES = ("apt", "apt-get", "snap install", "systemctl restart", "nginx")
        if any(cmd.lstrip().startswith(p) for p in SUDO_PREFIXES) and not cmd.startswith("sudo"):
            cmd = "sudo " + cmd

        log.info(f"执行命令: {cmd}")
        return run_shell(cmd, timeout=timeout, cwd=cwd)

    # ── blog_write ─────────────────────────────────────────────────────────[...]
    elif tool_name == "blog_write":
        title   = args.get("title", "")
        content = args.get("content", "")
        tags    = args.get("tags", "")
        draft   = args.get("draft", False)
        slug    = title.lower().replace(" ", "-").replace("/", "-")[:50]
        filename = f"{time.strftime('%Y-%m-%d')}-{slug}.md"
        filepath = f"{BLOG_DIR}/content/posts/{filename}"

        tag_list = [f'"{t.strip()}"' for t in tags.split(",") if t.strip()]
        frontmatter = f"""---
title: "{title}"
date: {time.strftime('%Y-%m-%dT%H:%M:%S+08:00')}
draft: {str(draft).lower()}
tags: [{", ".join(tag_list)}]
---

"""
        os.makedirs(f"{BLOG_DIR}/content/posts", exist_ok=True)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(frontmatter + content)
            return f"✅ 文章已保存：{filename}\n路径：{filepath}"
        except Exception as e:
            return f"❌ 保存失败: {e}"

    # ── blog_list ────────────────────────────────────────────────────────[...]
    elif tool_name == "blog_list":
        posts_dir = f"{BLOG_DIR}/content/posts"
        if not os.path.exists(posts_dir):
            return "📝 暂无文章（posts 目录不存在）"
        files = sorted(os.listdir(posts_dir), reverse=True)
        if not files:
            return "📝 暂无文章"
        lines = []
        for f in files[:20]:
            filepath = os.path.join(posts_dir, f)
            size = os.path.getsize(filepath)
            mtime = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(filepath)))
            lines.append(f"- {f} ({size}B, {mtime})")
        return f"📝 共 {len(files)} 篇文章：\n" + "\n".join(lines)

    # ── blog_publish ─────────────────────────────────────────────────────────
    elif tool_name == "blog_publish":
        push = args.get("push_github", False)
        result = run_shell("hugo", cwd=BLOG_DIR, timeout=60)
        if push and GITHUB_TOKEN and GITHUB_USER:
            git_cmds = [
                f"cd {BLOG_DIR}",
                "git add -A",
                f'git commit -m "Auto publish: {time.strftime("%Y-%m-%d %H:%M")}"',
                "git push"
            ]
            push_result = run_shell(" && ".join(git_cmds), timeout=60)
            result += f"\n\nGitHub 推送：\n{push_result}"
        return result

    # ── blog_delete ──────────────────────────────────────────────────────────[...]
    elif tool_name == "blog_delete":
        filename = args.get("filename", "")
        filepath = f"{BLOG_DIR}/content/posts/{filename}"
        if os.path.exists(filepath):
            os.remove(filepath)
            return f"✅ 已删除：{filename}"
        return f"❌ 文件不存在：{filename}"

    # ── github_repo_list ──────────────────────────────────────────────────────
    elif tool_name == "github_repo_list":
        if not GITHUB_TOKEN:
            return "❌ 未配置 GITHUB_TOKEN"
        rtype = args.get("type", "all")
        cmd = f'curl -s -H "Authorization: token {GITHUB_TOKEN}" "https://api.github.com/user/repos?type={rtype}&per_page=30"'
        output = run_shell(cmd)
        try:
            repos = json.loads(output.split("\n", 1)[-1])
            if isinstance(repos, list):
                lines = [f"- {r['name']} ({'私有' if r['private'] else '公开'}) {r.get('description','')}" for r in repos]
                return f"📦 共 {len(repos)} 个仓库：\n" + "\n".join(lines)
        except Exception:
            pass
        return output

    # ── github_file_write ─────────────────────────────────────────────────────
    elif tool_name == "github_file_write":
        if not GITHUB_TOKEN or not GITHUB_USER:
            return "❌ 未配置 GITHUB_TOKEN 或 GITHUB_USER"
        repo    = args.get("repo", "")
        path    = args.get("path", "")
        content = args.get("content", "")
        message = args.get("message", "Update via lark-agent")

        import base64
        b64content = base64.b64encode(content.encode()).decode()

        # 先获取文件 SHA（更新时需要）
        get_cmd = f'curl -s -H "Authorization: token {GITHUB_TOKEN}" "https://api.github.com/repos/{GITHUB_USER}/{repo}/contents/{path}"'
        get_result = run_shell(get_cmd)
        sha = ""
        try:
            existing = json.loads(get_result.split("\n", 1)[-1])
            sha = existing.get("sha", "")
        except Exception:
            pass

        payload = {"message": message, "content": b64content}
        if sha:
            payload["sha"] = sha

        put_cmd = f'''curl -s -X PUT -H "Authorization: token {GITHUB_TOKEN}" \
            -H "Content-Type: application/json" \
            -d '{json.dumps(payload)}' \
            "https://api.github.com/repos/{GITHUB_USER}/{repo}/contents/{path}"'''
        result = run_shell(put_cmd)
        if '"content"' in result:
            return f"✅ 文件已{'更新' if sha else '创建'}：{path}"
        return f"❌ 操作失败：{result[:200]}"

    # ── github_repo_create ────────────────────────────────────────────────────
    elif tool_name == "github_repo_create":
        if not GITHUB_TOKEN:
            return "❌ 未配置 GITHUB_TOKEN"
        name    = args.get("name", "")
        desc    = args.get("description", "")
        private = args.get("private", False)
        payload = {"name": name, "description": desc, "private": private, "auto_init": True}
        cmd = f'''curl -s -X POST -H "Authorization: token {GITHUB_TOKEN}" \
            -d '{json.dumps(payload)}' \
            "https://api.github.com/user/repos"'''
        result = run_shell(cmd)
        if '"full_name"' in result:
            return f"✅ 仓库已创建：https://github.com/{GITHUB_USER}/{name}"
        return f"❌ 创建失败：{result[:200]}"

    # ── tool_create ──────────────────────────────────────────────────────────[...]
    elif tool_name == "tool_create":
        if not is_admin:
            return "❌ 权限不足"
        name   = args.get("name", "").replace(" ", "_")
        desc   = args.get("description", "")
        script = args.get("script", "")
        lang   = args.get("lang", "bash")
        params = args.get("params_desc", "{}")

        if not name or not script:
            return "❌ name 和 script 不能为空"

        # 保存工具脚本到文件
        script_dir = "/opt/lark-agent/tools"
        os.makedirs(script_dir, exist_ok=True)
        ext = "sh" if lang == "bash" else "py"
        script_path = f"{script_dir}/{name}.{ext}"

        with open(script_path, "w") as f:
            if lang == "bash":
                f.write("#!/bin/bash\n" + script)
            else:
                f.write("#!/usr/bin/env python3\n" + script)
        os.chmod(script_path, 0o755)

        # 注册到数据库
        tools_db[name] = {
            "description": desc,
            "script_path": script_path,
            "lang":        lang,
            "params_desc": params,
            "created_at":  time.time(),
            "created_by":  user_id
        }
        log.info(f"新工具已注册: {name}")
        return f"✅ 工具 [{name}] 已创建并注册\n脚本路径：{script_path}\n描述：{desc}"

    # ── tool_list ────────────────────────────────────────────────────────────[...]
    elif tool_name == "tool_list":
        if not tools_db:
            return "📦 暂无自定义工具"
        lines = []
        for name, info in tools_db.items():
            t = time.strftime("%Y-%m-%d", time.localtime(info.get("created_at", 0)))
            lines.append(f"- [{name}] {info['description']} ({info['lang']}, {t})")
        return "📦 自定义工具列表：\n" + "\n".join(lines)

    # ── tool_run ─────────────────────────────────────────────────────────[...]
    elif tool_name == "tool_run":
        name = args.get("name", "")
        tool_args = args.get("args", "{}")
        if name not in tools_db:
            return f"❌ 工具不存在：{name}"
        tool_info = tools_db[name]
        script_path = tool_info["script_path"]
        lang = tool_info["lang"]

        if lang == "bash":
            cmd = f"bash {script_path} '{tool_args}'"
        else:
            cmd = f"/opt/lark-agent/venv/bin/python3 {script_path} '{tool_args}'"

        log.info(f"运行自定义工具: {name}")
        return run_shell(cmd, timeout=60)

    # ── tool_delete ──────────────────────────────────────────────────────────[...]
    elif tool_name == "tool_delete":
        if not is_admin:
            return "❌ 权限不足"
        name = args.get("name", "")
        if name not in tools_db:
            return f"❌ 工具不存在：{name}"
        script_path = tools_db[name].get("script_path", "")
        if script_path and os.path.exists(script_path):
            os.remove(script_path)
        del tools_db[name]
        return f"✅ 工具 [{name}] 已删除"

    # ── remember ─────────────────────────────────────────────────────────[...]
    elif tool_name == "remember":
        key   = args.get("key", "")
        value = args.get("value", "")
        memory_db[f"{user_id}:{key}"] = {"value": value, "timestamp": time.time()}
        return f"✅ 已记住：{key}"

    # ── recall ──────────────────────────────────────────────────────────[...]
    elif tool_name == "recall":
        key = args.get("key", "").lower()
        results = [
            f"{k.split(':', 1)[-1]}: {v['value']}"
            for k, v in memory_db.items()
            if user_id in k and key in k.lower()
        ]
        return ("📝 找到：\n" + "\n".join(results)) if results else f"未找到：{key}"

    # ── update_system_prompt ──────────────────────────────────────────────────
    elif tool_name == "update_system_prompt":
        if not is_admin:
            return "❌ 权限不足"
        new_prompt = args.get("new_prompt", "")
        reason     = args.get("reason", "")
        old_prompt = _current_system_prompt
        _current_system_prompt = new_prompt
        evolution_db[f"evo_{int(time.time())}"] = {
            "timestamp": time.time(), "reason": reason,
            "old_prompt": old_prompt, "new_prompt": new_prompt,
            "triggered_by": user_id
        }
        return f"✅ 提示词已更新\n原因：{reason}"

    # ── get_agent_status ──────────────────────────────────────────────────────
    elif tool_name == "get_agent_status":
        disk = run_shell("df -h / | tail -1 | awk '{print $3\"/\"$2}'")
        mem  = run_shell("free -h | grep Mem | awk '{print $3\"/\"$2}'")
        return (
            f"🤖 Agent 状态\n"
            f"模型：{GEMINI_MODEL}\n"
            f"活跃用户：{len(history_db)}\n"
            f"长期记忆：{len(memory_db)} 条\n"
            f"自定义工具：{len(tools_db)} 个\n"
            f"进化次数：{len(evolution_db)}\n"
            f"内存：{mem.strip()}\n"
            f"磁盘：{disk.strip()}"
        )

    return f"未知工具: {tool_name}"


# ════════════════════════════════════════════════════════════════[...]
# Gemini 调用
# ══════════════════════════════════════════════���═════════════════[...]

def call_gemini_sync(user_id: str, user_message: str) -> str:
    credentials = service_account.Credentials.from_service_account_file(
        CREDENTIALS_FILE,
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    vertexai.init(project=GCP_PROJECT_ID, location=GCP_LOCATION, credentials=credentials)

    pref = preference_db.get(user_id, "")
    user_memories = [v["value"] for k, v in memory_db.items() if k.startswith(user_id + ":")]
    memory_summary = "\n".join(f"- {m}" for m in user_memories[-5:])

    dynamic_prompt = _current_system_prompt
    if pref:
        dynamic_prompt += f"\n\n用户偏好：{pref}"
    if memory_summary:
        dynamic_prompt += f"\n\n用户长期记忆：\n{memory_summary}"

    model = GenerativeModel(
        GEMINI_MODEL,
        system_instruction=dynamic_prompt,
        tools=[build_tools()]
    )

    raw_history = history_db.get(user_id, [])
    history = [
        Content(role=t["role"], parts=[Part.from_text(t["text"])])
        for t in raw_history[-(MAX_HISTORY_TURNS * 2):]
    ]

    chat  = model.start_chat(history=history, response_validation=False)
    message = user_message

    for _ in range(8):  # 最多8轮工具调用
        response  = chat.send_message(message)
        candidate = response.candidates[0]

        tool_calls = [
            p for p in candidate.content.parts
            if hasattr(p, "function_call")
            and p.function_call is not None
            and p.function_call.name
        ]

        if not tool_calls:
            break

        tool_results = []
        for part in tool_calls:
            fc     = part.function_call
            result = execute_tool(fc.name, dict(fc.args), user_id)
            log.info(f"工具 [{fc.name}] → {result[:60]}")
            tool_results.append(Part.from_function_response(
                name=fc.name, response={"result": result}
            ))
        message = tool_results

    reply = "".join(
        p.text for p in candidate.content.parts
        if hasattr(p, "text") and p.text
    ).strip() or "（无回复）"

    updated = list(raw_history)
    updated.append({"role": "user",  "text": user_message})
    updated.append({"role": "model", "text": reply})
    history_db[user_id] = updated[-(MAX_HISTORY_TURNS * 2):]

    return reply


# ════════════════════════════════════════════════════════════════[...]
# 发消息
# ════════════════════════════════════════════════════════════════[...]

def send_text_message(receive_id: str, text: str, receive_id_type: str = "open_id"):
    request = CreateMessageRequest.builder() \
        .receive_id_type(receive_id_type) \
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(receive_id)
            .msg_type("text")
            .content(json.dumps({"text": text}))
            .build()
        ).build()
    resp = lark_client.im.v1.message.create(request)
    if not resp.success():
        log.warning(f"发送失败: {resp.code} {resp.msg}")


# ════════════════════════════════════════════════════════════════[...]
# 内置指令
# ════════════════════════════════════════════════════════════════[...]

def handle_command(user_id: str, text: str):
    global GEMINI_MODEL
    cmd = text.strip().lower()
    if cmd == "/clear":
        if user_id in history_db: del history_db[user_id]
        return "✅ 对话历史已清除"
    if cmd == "/status":
        return execute_tool("get_agent_status", {}, user_id)
    if cmd == "/tools":
        return execute_tool("tool_list", {}, user_id)
    if cmd == "/memory":
        items = [(k, v) for k, v in memory_db.items() if k.startswith(user_id + ":")]
        if not items: return "📝 暂无长期记忆"
        return "📝 长期记忆：\n" + "\n".join(f"- {k.split(':',1)[-1]}: {v['value']}" for k, v in items)
    if cmd.startswith("/preference "):
        pref = text[len("/preference "):].strip()
        preference_db[user_id] = pref
        return f"✅ 偏好已更新：{pref}"
    if cmd.startswith("/model"):
        parts = text.strip().split()
        # /model 不带参数：显示当前和可用模型
        if len(parts) == 1:
            available = [
                "gemini-2.5-flash      (推荐，工具调用稳定)",
                "gemini-2.5-pro        (最强，慢一些)",
                "gemini-2.5-flash-lite (最省钱，工具调用弱)",
            ]
            return (
                f"🤖 当前模型：{GEMINI_MODEL}\n\n"
                f"可用模型：\n" + "\n".join(f"  {m}" for m in available) + "\n\n"
                f"切换示例：/model gemini-2.5-pro"
            )
        # /model <名称>：切换模型
        new_model = parts[1]
        ALLOWED_MODELS = {
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash",
        }
        if new_model not in ALLOWED_MODELS:
            return f"❌ 不支持的模型：{new_model}\n发送 /model 查看可用列表"
        #global GEMINI_MODEL
        GEMINI_MODEL = new_model
        return f"✅ 模型已切换为：{new_model}"
    if cmd == "/help":
        return (
            "🤖 指令列表：\n"
            "/clear          清除对话历史\n"
            "/status         Agent 状态\n"
            "/model          查看/切换模型\n"
            "/tools          自定义工具列表\n"
            "/memory         长期记忆\n"
            "/preference <x> 设置偏好\n"
            "/help           帮助\n\n"
            "💡 对话示例：\n"
            "「帮我写一篇关于Python的博客并发布」\n"
            "「列出我的GitHub仓库」\n"
            "「创建一个工具，每天统计博客访问量」\n"
            "「查看服务器内存使用情况」"
        )
    return None


# ════════════════════════════════════════════════════════════════[...]
# 事件处理
# ════════════════════════════════════════════════════════════════[...]

def do_p2_im_message_receive_v1(data) -> None:
    message = data.event.message
    sender  = data.event.sender

    if message.message_type != "text":
        return

    message_id = message.message_id
    if message_id in processed_message_ids:
        return
    processed_message_ids.add(message_id)
    if len(processed_message_ids) > 1000:
        for mid in list(processed_message_ids)[:500]:
            processed_message_ids.discard(mid)

    user_open_id = sender.sender_id.open_id
    chat_id      = message.chat_id
    chat_type    = message.chat_type
    if not user_open_id:
        return

    try:
        content   = json.loads(message.content)
        user_text = content.get("text", "").strip()
        if "@_user_" in user_text:
            user_text = " ".join(w for w in user_text.split() if not w.startswith("@_user_")).strip()
    except Exception:
        return

    if not user_text:
        return

    log.info(f"收到消息 [{user_open_id[:8]}...]: {user_text}")

    reply = handle_command(user_open_id, user_text)
    if reply is None:
        try:
            reply = call_gemini_sync(user_open_id, user_text)
        except Exception as e:
            log.error(f"Gemini 调用失败: {e}", exc_info=True)
            reply = "抱歉，AI 服务暂时异常，请稍后再试。"

    target_id   = user_open_id if chat_type == "p2p" else chat_id
    id_type     = "open_id"    if chat_type == "p2p" else "chat_id"
    send_text_message(target_id, reply, id_type)


# ════════════════════════════════════════════════════════════════[...]
# 启动
# ════════════════════════════════════════════════════════════════[...]

def cleanup_db():
    cutoff = time.time() - 30 * 86400
    stale_mem = [k for k, v in memory_db.items() if v.get("timestamp", 0) < cutoff]
    for k in stale_mem:
        del memory_db[k]
    evo_keys = sorted(evolution_db.keys())
    for k in evo_keys[:-50]:
        del evolution_db[k]
    users = list(history_db.keys())
    if len(users) > 200:
        for k in users[:-200]:
            del history_db[k]
    log.info(f"数据库清理完成，清理记忆 {len(stale_mem)} 条")


def main():
    cleanup_db()
    log.info(f"模型: {GEMINI_MODEL} | 博客目录: {BLOG_DIR}")
    log.info(f"GitHub: {GITHUB_USER or '未配置'} | 管理员: {ADMIN_USERS or '未配置'}")
    log.info(f"自定义工具: {len(tools_db)} 个")

    event_handler = lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1) \
        .build()

    ws_client = lark.ws.Client(
        LARK_APP_ID, LARK_APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
        domain=lark.LARK_DOMAIN,
    )
    ws_client.start()


if __name__ == "__main__":
    main()
