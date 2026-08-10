# CopDem

A small Python static site, auto-deployed to GitHub Pages.

## Local dev

```bash
python -m venv .venv
.venv/Scripts/activate  # Windows
pip install -r requirements.txt
python build_site.py
```

Output goes to `site/`. Open `site/index.html` in a browser to preview.

## Content

Edit or add Markdown files under `content/`. Each file needs a small front
matter block:

```
title: Page Title
---
# Heading

Body text...
```

## Deployment

Pushing to `main` triggers [.github/workflows/deploy.yml](.github/workflows/deploy.yml),
which builds the site and publishes it to GitHub Pages automatically.
