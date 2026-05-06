#!/bin/bash
#!/bin/bash
cd /var/www/blog

# 确保在博客目录下
if [ ! -d "./public" ]; then
    echo "Error: Not in a Hugo blog directory." >&2
    exit 1
fi

# 清理旧的构建产物
rm -rf public

echo "Building blog with /home/lark-agent/.local/bin/hugo..."
/home/lark-agent/.local/bin/hugo

if [ $? -ne 0 ]; then
    echo "Error: Hugo build failed." >&2
    exit 1
fi

echo "Hugo build successful."

if [ "$1" == "true" ]; then
    echo "Pushing to GitHub..."
    git add public/
    git commit -m "Auto publish blog post on $(date +'%Y-%m-%d %H:%M')" || true # `|| true` to prevent error if no changes
    git push origin main
    if [ $? -ne 0 ]; then
        echo "Git push failed, attempting to set upstream..."
        git push --set-upstream origin main
    fi
    echo "GitHub push process completed."
else
    echo "Skipping GitHub push as requested."
fi

