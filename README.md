# Lark Agent Custom Tools and Configurations

This repository stores custom tools and important configuration backups for the Lark Agent.

## How to Recreate `blog_publish_hugo_v161` Tool

If for any reason the `blog_publish_hugo_v161` tool needs to be recreated, you can use the following steps:

1.  **Retrieve the script content:**
    The script content is located at `tools/blog_publish_hugo_v161.sh` in this repository.

2.  **Use the `tool_create` function:**
    Call the `tool_create` API with the following parameters, replacing `[SCRIPT_CONTENT]` with the actual content from `tools/blog_publish_hugo_v161.sh`:

    ```python
    default_api.tool_create(
        name='blog_publish_hugo_v161',
        description='Builds and publishes the Hugo blog using v0.161.1, with optional GitHub Pages push.',
        lang='bash',
        script='''[SCRIPT_CONTENT]''',
        params_desc='''{"push_github": {"type": "boolean", "description": "Whether to push to GitHub Pages after building, default false"}}'''
    )
    ```

    **Important:** When copying the script content into the `script` argument, ensure to properly escape any triple single quotes (`'''`) within the script itself to `\'\'` if they exist.

## Environment Notes

*   **Hugo Version:** Hugo v0.161.1 is installed at `/home/lark-agent/.local/bin/hugo`.
*   **Blog Root:** The blog content and static files are managed in `/var/www/blog`.
*   **GitHub Credentials:** `GITHUB_TOKEN` and `GITHUB_USER` are configured as environment variables for the agent.
