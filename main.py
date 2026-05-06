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

# ─── 日志 ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ─── 配置 ────────────────────────────────────────────────────────────────────
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

# ─── 持久化存储 ───────────────────────────────────────────────────────────────
history_db    = SqliteDict(DB_PATH, tablename="history",     autocommit=True)
preference_db = SqliteDict(DB_PATH, tablename="preferences", autocommit=True)
memory_db     = SqliteDict(DB_PATH, tablename="memory",      autocommit=True)
evolution_db  = SqliteDict(DB_PATH, tablename="evolution",   autocommit=True)
tools_db      = SqliteDict(DB_PATH, tablename="custom_tools", autocommit=True)  # 动态工具库

# ─── 消息去重 ─────────────────────────────────────────────────────────────────
processed_message_ids: set = set()

# ─── 运行时可变状态 ───────────────────────────────────────────────────────────
_current_system_prompt = SYSTEM_PROMPT

# ─── Lark 客户端 ──────────────────────────────────────────────────────────────
lark_client = lark.Client.builder() \
    .app_id(LARK_APP_ID) \
    .app_secret(LARK_APP_SECRET) \
    .domain(lark.LARK_DOMAIN) \
    .build()


# ═══════════════════════════════════════════════════════════════════════════════
# Shell 执行（基础能力）
# ═══════════════════════════════════════════════════════════════════════════════

def run_shell(command: str, timeout: int = 30, cwd: str = None) -> str:
    """执行 shell 命令，返回结果"""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True,
