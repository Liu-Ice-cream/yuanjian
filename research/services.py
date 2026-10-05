import html
import re
from urllib.parse import quote

from django.db.models import Q

from .models import ResearchItem


def research_record_condition():
    # Match the model's whitespace check, including old/imported empty cards.
    return Q(research_item__question__regex=r"\S") | Q(
        research_item__conclusion__regex=r"\S"
    )


def decorate_material(bookmark):
    item = getattr(bookmark, "research_item", None)
    bookmark.card = item
    bookmark.has_research_record = bool(item and item.has_research_record)
    bookmark.material_label = item.get_material_type_display() if item else "未分类"
    bookmark.stage = (
        item.effective_stage
        if item
        else (
            ResearchItem.ReadingStage.COLLECTED
            if bookmark.unread
            else ResearchItem.ReadingStage.REVIEWED
        )
    )
    bookmark.stage_label = ResearchItem.ReadingStage(bookmark.stage).label
    return bookmark


def markdown_text(value):
    value = html.escape(str(value), quote=False)
    return re.sub(r"([\\`*_{}\[\]#!|])", r"\\\1", value)


def export_markdown(bookmarks, title, generated_at):
    yield f"# {markdown_text(' '.join(title.splitlines()))}\n\n源笺 · 研究材料清单\n\n生成时间：{generated_at}\n\n"
    count = 0
    for bookmark in bookmarks.iterator(chunk_size=200):
        decorate_material(bookmark)
        count += 1
        item = bookmark.card
        safe_url = quote(bookmark.url, safe=":/?=&%#@+~,;!$-_.")
        yield f"## {count}. {markdown_text(' '.join(bookmark.resolved_title.splitlines()))}\n\n"
        yield f"原始来源：[打开资料](<{safe_url}>)\n\n"
        yield f"资料类型：{bookmark.material_label}  \n阅读阶段：{bookmark.stage_label}  \n"
        yield f"所属课题：{markdown_text(item.project.name) if item and item.project else '未归入课题'}\n\n"
        sections = [("简要介绍", bookmark.description)]
        if item:
            sections += [
                ("研究问题", item.question),
                ("核心结论", item.conclusion),
                ("证据与实验", item.evidence),
                ("局限与注意事项", item.limitations),
                ("与课题的关系", item.relevance),
            ]
        sections.append(("补充笔记", bookmark.notes))
        for label, value in sections:
            if value:
                yield f"### {label}\n\n"
                yield (
                    "\n".join("> " + markdown_text(line) for line in value.splitlines())
                    + "\n\n"
                )
        excerpts = getattr(bookmark, "active_excerpts", None)
        if excerpts is None:
            excerpts = bookmark.research_excerpts.filter(is_archived=False)
        for excerpt in excerpts:
            yield f"### 研究摘录 · {markdown_text(' '.join(excerpt.locator.splitlines()))}\n\n"
            yield "原文摘录：\n\n"
            yield (
                "\n".join(
                    "> " + markdown_text(line)
                    for line in excerpt.original_text.splitlines()
                )
                + "\n\n"
            )
            yield "我的理解：\n\n"
            yield (
                "\n".join(
                    "> " + markdown_text(line)
                    for line in excerpt.interpretation.splitlines()
                )
                if excerpt.interpretation
                else "尚未记录。"
            ) + "\n\n"
        if bookmark.tag_names:
            yield (
                "标签："
                + "、".join(markdown_text(tag) for tag in bookmark.tag_names)
                + "\n\n"
            )
        yield "---\n\n"
    if count == 0:
        yield "当前筛选条件下没有资料。\n"


def export_excerpts_markdown(excerpts, title, generated_at):
    yield f"# {markdown_text(' '.join(title.splitlines()))}\n\n源笺 · 研究摘录清单\n\n生成时间：{generated_at}\n\n"
    for count, excerpt in enumerate(excerpts.iterator(chunk_size=200), start=1):
        bookmark = excerpt.bookmark
        item = getattr(bookmark, "research_item", None)
        safe_url = quote(bookmark.url, safe=":/?=&%#@+~,;!$-_.")
        yield f"## {count}. {markdown_text(' '.join(bookmark.resolved_title.splitlines()))}\n\n"
        yield f"原始来源：[打开资料](<{safe_url}>)\n\n"
        yield f"来源位置：{markdown_text(' '.join(excerpt.locator.splitlines()))}\n\n"
        yield f"所属课题：{markdown_text(item.project.name) if item and item.project else '未归入课题'}\n\n"
        yield "### 原文摘录\n\n"
        yield (
            "\n".join(
                "> " + markdown_text(line)
                for line in excerpt.original_text.splitlines()
            )
            + "\n\n"
        )
        yield "### 我的理解\n\n"
        yield (
            "\n".join(
                "> " + markdown_text(line)
                for line in excerpt.interpretation.splitlines()
            )
            if excerpt.interpretation
            else "尚未记录。"
        ) + "\n\n---\n\n"
