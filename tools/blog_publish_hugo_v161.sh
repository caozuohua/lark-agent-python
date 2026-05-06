#!/bin/bash
set -e

# Parse arguments
PUSH_GITHUB=false
if [[ "$*" == *"--push_github"* ]]; then
    PUSH_GITHUB=true
fi

echo "Building blog with Hugo v0.161.1..."
# Ensure we use the specific Hugo version
/home/lark-agent/.local/bin/hugo -s /var/www/blog

if [ $? -ne 0 ]; then
    echo "Hugo build failed."
    exit 1
fi

echo "Hugo build successful."

if [ "$PUSH_GITHUB" = true ]; then
    echo "Pushing to GitHub Pages..."
    cd /var/www/blog/public
    git add .
    git commit -m "Publish blog updates via blog_publish_hugo_v161 tool" || true # || true to prevent error if no changes
    git push origin main
    if [ $? -ne 0 ]; then
        echo "GitHub push failed."
        exit 1
    fi
    echo "GitHub push successful."
else
    echo "Skipping GitHub push as --push_github flag was not provided."
fi
