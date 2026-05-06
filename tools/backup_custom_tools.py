#!/usr/bin/env python3
import json

def backup_tools():
    tools = default_api.tool_list()
    custom_tools = []
    for tool in tools.get('tool_list_response', {}).get('tools', []):
        # 假设自定义工具的定义包含 script 字段，且不是内置工具
        if 'script' in tool and tool.get('name') not in ['run_shell', 'blog_write', 'blog_list', 'blog_publish', 'blog_delete', 'github_repo_list', 'github_file_write', 'github_repo_create', 'tool_create', 'tool_list', 'tool_run', 'tool_delete', 'remember', 'recall', 'update_system_prompt', 'get_agent_status', 'send_file']:
            custom_tools.append({
                'name': tool.get('name'),
                'description': tool.get('description'),
                'script': tool.get('script'),
                'lang': tool.get('lang'),
                'params_desc': tool.get('params_desc')
            })
    
    backup_content = json.dumps(custom_tools, indent=2)
    
    default_api.github_file_write(
        repo='agent-configs',
        path='custom_tools_backup.json',
        content=backup_content,
        message='Backup of custom tools'
    )
    print(f'Custom tools backup pushed to agent-configs/custom_tools_backup.json')

backup_tools()