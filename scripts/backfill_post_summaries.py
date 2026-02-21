#!/usr/bin/env python3

import os
import re
from typing import List, Tuple

from common.config import setup_logging


logger = setup_logging("backfill_post_summaries")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
POSTS_DIR = os.path.join(REPO_ROOT, "_posts")
SUMMARY_TITLE = "전체 뉴스 요약"

SECTION_PRIORITY = [
    "핵심 요약",
    "오늘의 핵심",
    "뉴스 내용 기반 핵심 요약",
    "시장 인사이트",
    "오늘의 시장 인사이트",
    "시장 개요",
    "규제 인사이트",
    "정책 영향 분석",
    "소셜 동향 분석",
    "DeFi 시장 인사이트",
    "한눈에 보기",
]


def split_frontmatter(content: str) -> Tuple[str, str]:
    if not content.startswith("---\n"):
        return "", content
    parts = content.split("---\n", 2)
    if len(parts) < 3:
        return "", content
    front = "---\n" + parts[1] + "---\n"
    body = parts[2]
    return front, body


def clean_text(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[(.+?)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def is_noise_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped in {"---", "--", "-", "*"}:
        return True
    if re.match(r"^\*?총\s*\d+건\s*수집\*?$", stripped):
        return True
    if stripped.startswith("데이터 수집"):
        return True
    return False


def find_heading_index(lines: List[str], title: str) -> int:
    pattern = re.compile(rf"^##\s+{re.escape(title)}\s*$")
    for idx, line in enumerate(lines):
        if pattern.match(line.strip()):
            return idx
    return -1


def find_section_end(lines: List[str], start_idx: int) -> int:
    for idx in range(start_idx + 1, len(lines)):
        if re.match(r"^##\s+", lines[idx].strip()):
            return idx
    return len(lines)


def extract_section_bullets(lines: List[str], title: str, limit: int = 3) -> List[str]:
    idx = find_heading_index(lines, title)
    if idx == -1:
        return []
    end = find_section_end(lines, idx)
    bullets: List[str] = []
    for line in lines[idx + 1 : end]:
        raw = line.strip()
        if raw.startswith("- ") or raw.startswith("* "):
            cleaned = clean_text(raw[2:])
            if cleaned and not is_noise_text(cleaned):
                bullets.append(cleaned)
        if len(bullets) >= limit:
            break
    return bullets


def extract_section_sentences(
    lines: List[str], title: str, limit: int = 2
) -> List[str]:
    idx = find_heading_index(lines, title)
    if idx == -1:
        return []
    end = find_section_end(lines, idx)
    results: List[str] = []
    for line in lines[idx + 1 : end]:
        raw = line.strip()
        if not raw:
            if results:
                break
            continue
        if raw.startswith(("#", "|", "!", "<", ">")):
            continue
        if raw.startswith("- ") or raw.startswith("* "):
            continue
        cleaned = clean_text(raw)
        if cleaned and not is_noise_text(cleaned):
            if len(cleaned) > 160:
                cleaned = cleaned[:157] + "..."
            results.append(cleaned)
        if len(results) >= limit:
            break
    return results


def extract_theme_names(lines: List[str]) -> List[str]:
    names: List[str] = []

    idx = find_heading_index(lines, "테마 스냅샷")
    if idx != -1:
        end = find_section_end(lines, idx)
        for line in lines[idx + 1 : end]:
            if not line.strip().startswith("|"):
                continue
            if "| ---" in line or "| 테마" in line:
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells:
                theme = clean_text(cells[0])
                if theme and theme not in names:
                    names.append(theme)
            if len(names) >= 3:
                return names

    label_pattern = re.compile(r"theme-label\">([^<]+)")
    for line in lines:
        match = label_pattern.search(line)
        if not match:
            continue
        label = clean_text(match.group(1))
        if label and label not in names:
            names.append(label)
        if len(names) >= 3:
            break

    return names


def extract_total_count(body: str) -> str:
    patterns = [
        r"총\s*\*\*(\d{1,6})\*\*\s*건",
        r"총\s*(\d{1,6})\s*건",
        r"총\s*수집[^\d]*(\d{1,6})\s*건",
        r"수집\s*건수\s*[:：]?\s*(\d{1,6})",
        r"(?:뉴스|이슈)\s*(\d{1,6})\s*건",
        r"(\d{1,6})\s*건\s*을\s*정리",
    ]
    for pattern in patterns:
        match = re.search(pattern, body)
        if match:
            return match.group(1)
    return ""


def extract_intro_bullets(lines: List[str], limit: int = 2) -> List[str]:
    paragraphs: List[str] = []
    buffer: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if buffer:
                paragraphs.append(" ".join(buffer))
                buffer = []
            continue
        if stripped.startswith(("#", "|", "!", "<", ">")):
            continue
        if stripped in {"---", "--"}:
            continue
        buffer.append(stripped)
    if buffer:
        paragraphs.append(" ".join(buffer))

    bullets: List[str] = []
    for para in paragraphs[:2]:
        cleaned = clean_text(para)
        if len(cleaned) > 160:
            cleaned = cleaned[:157] + "..."
        if cleaned and not is_noise_text(cleaned):
            bullets.append(cleaned)
        if len(bullets) >= limit:
            break
    return bullets


def build_summary(lines: List[str], body: str) -> List[str]:
    summary: List[str] = []
    total = extract_total_count(body)
    if total:
        summary.append(f"총 **{total}건** 수집")

    theme_names = extract_theme_names(lines)
    if theme_names:
        summary.append(f"주요 테마: {', '.join(theme_names)}")

    used = set(summary)

    for section in SECTION_PRIORITY:
        for bullet in extract_section_bullets(lines, section, limit=3):
            if bullet in used:
                continue
            if total and total in bullet and ("총" in bullet or "수집" in bullet):
                continue
            summary.append(bullet)
            used.add(bullet)
            if len(summary) >= 4:
                return summary
        for sentence in extract_section_sentences(lines, section, limit=2):
            if sentence in used:
                continue
            summary.append(sentence)
            used.add(sentence)
            if len(summary) >= 4:
                return summary

    if len(summary) < 3:
        for bullet in extract_intro_bullets(lines, limit=3):
            if bullet in used:
                continue
            summary.append(bullet)
            used.add(bullet)
            if len(summary) >= 4:
                break

    return summary[:4]


def insert_summary(lines: List[str], summary_lines: List[str]) -> List[str]:
    if not summary_lines:
        return lines

    summary_block = [f"## {SUMMARY_TITLE}", ""]
    summary_block.extend([f"- {line}" for line in summary_lines])
    summary_block.append("")

    for title in ("한눈에 보기", "핵심 요약"):
        idx = find_heading_index(lines, title)
        if idx != -1:
            end = find_section_end(lines, idx)
            return lines[:end] + [""] + summary_block + lines[end:]

    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    end = start
    while end < len(lines) and lines[end].strip():
        end += 1
    return lines[:end] + [""] + summary_block + lines[end:]


def remove_existing_summary(lines: List[str]) -> Tuple[List[str], bool]:
    idx = find_heading_index(lines, SUMMARY_TITLE)
    if idx == -1:
        return lines, False
    end = find_section_end(lines, idx)
    return lines[:idx] + lines[end:], True


def process_post(filepath: str) -> bool:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    front, body = split_frontmatter(content)
    if not body:
        return False

    lines = body.splitlines()
    stripped_lines, _ = remove_existing_summary(lines)
    rebuilt_body = "\n".join(stripped_lines)
    summary_lines = build_summary(stripped_lines, rebuilt_body)
    updated_lines = insert_summary(stripped_lines, summary_lines)

    if updated_lines == lines:
        return False

    updated_content = front + "\n".join(updated_lines).rstrip() + "\n"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(updated_content)
    return True


def main() -> None:
    if not os.path.isdir(POSTS_DIR):
        logger.warning("Posts directory not found: %s", POSTS_DIR)
        return

    updated = 0
    total = 0
    for filename in sorted(os.listdir(POSTS_DIR)):
        if not filename.endswith(".md"):
            continue
        total += 1
        filepath = os.path.join(POSTS_DIR, filename)
        if process_post(filepath):
            updated += 1

    logger.info("Checked %d posts, updated %d", total, updated)


if __name__ == "__main__":
    main()
