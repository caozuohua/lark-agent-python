#!/bin/bash
#!/bin/bash
set -e

BLOG_DIR="/var/www/blog"
HUGO_BIN="/home/lark-agent/.local/bin/hugo"

echo "==> Changing to blog directory: $BLOG_DIR"
cd $BLOG_DIR

echo "==> Building site with correct Hugo: $HUGO_BIN"
# Using --cleanDestinationDir to ensure a clean build
$HUGO_BIN -D --cleanDestinationDir

echo "==> Changing to public directory for deployment"
cd "$BLOG_DIR/public"

echo "==> Deploying to GitHub Pages"
if [ -n "$(git status --porcelain)" ]; then
  git add .
  git commit -m "Site publish by Agent on $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  git push
  echo "==> Successfully published to GitHub Pages."
else
  echo "==> No changes to publish."
fi
