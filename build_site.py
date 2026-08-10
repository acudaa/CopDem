#!/usr/bin/env python3
"""Tiny static site generator.

Reads Markdown files from content/, renders each through templates/base.html,
and writes the result to site/. Front matter is a simple "key: value" block
followed by a "---" line, e.g.:

    title: Home
    ---
    # Heading
    Body text...
"""
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).parent
CONTENT_DIR = ROOT / "content"
TEMPLATES_DIR = ROOT / "templates"
OUTPUT_DIR = ROOT / "site"


def parse_front_matter(text: str) -> tuple[dict, str]:
    meta: dict[str, str] = {}
    if "\n---\n" in text:
        head, body = text.split("\n---\n", 1)
        for line in head.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip()
        return meta, body
    return meta, text


def build() -> None:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("base.html")

    OUTPUT_DIR.mkdir(exist_ok=True)

    for md_file in CONTENT_DIR.rglob("*.md"):
        raw = md_file.read_text(encoding="utf-8")
        meta, body = parse_front_matter(raw)
        html_body = markdown.markdown(body, extensions=["fenced_code", "tables"])
        rendered = template.render(title=meta.get("title", md_file.stem), content=html_body)

        rel = md_file.relative_to(CONTENT_DIR).with_suffix(".html")
        out_path = OUTPUT_DIR / (rel if rel.name != "index.html" else rel)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
        print(f"built {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    build()
