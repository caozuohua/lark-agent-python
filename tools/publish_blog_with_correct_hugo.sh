#!/bin/bash
#!/bin/bash

# Define variables
BLOG_DIR="/var/www/blog"
HUGO_BIN="/home/lark-agent/bin/hugo"
PUBLIC_DIR="${BLOG_DIR}/public"
COMMIT_MESSAGE="Publish blog post"

# Check if push_github argument is true
PUSH_GITHUB=false
if [ "$1" = "true" ]; then
    PUSH_GITHUB=true
fi

# 1. Clean public directory
rm -rf "${PUBLIC_DIR}"

# 2. Build the Hugo site
echo "Building Hugo site in ${BLOG_DIR}..."
"${HUGO_BIN}" --source "${BLOG_DIR}" --destination "${PUBLIC_DIR}"

if [ $? -ne 0 ]; then
    echo "❌ Hugo build failed!"
    exit 1
fi
echo "✅ Hugo build successful!"

# 3. If push_github is true, commit and push to GitHub Pages
if $PUSH_GITHUB; then
    echo "Pushing to GitHub Pages..."
    cd "${BLOG_DIR}"
    git add .
    git commit -m "${COMMIT_MESSAGE}"
    git push origin main # Assuming 'main' branch for GitHub Pages
    if [ $? -ne 0 ]; then
        echo "❌ GitHub push failed!"
        exit 1
    fi
    echo "✅ Successfully pushed to GitHub Pages!"
else
    echo "Skipping GitHub push as requested."
fi

echo "Blog publication process completed."
