from urllib.parse import quote

from django.db.models import Count, Max, Prefetch, Q

from .models import ResearchExcerpt, ResearchGroup, ResearchPlacement
from .services import markdown_text


def available_excerpts(project):
    return ResearchExcerpt.objects.filter(
        bookmark__owner=project.owner,
        bookmark__research_item__project=project,
        bookmark__is_archived=False,
        is_archived=False,
    ).select_related("bookmark", "bookmark__research_item")


def available_placements(project):
    return ResearchPlacement.objects.filter(
        group__project=project,
        group__is_archived=False,
        is_archived=False,
        excerpt__bookmark__owner=project.owner,
        excerpt__bookmark__research_item__project=project,
        excerpt__bookmark__is_archived=False,
        excerpt__is_archived=False,
    ).select_related("excerpt", "excerpt__bookmark")


def outlined_groups(project):
    return (
        ResearchGroup.objects.filter(project=project, is_archived=False)
        .annotate(
            saved_count=Count("placements", filter=Q(placements__is_archived=False))
        )
        .prefetch_related(
            Prefetch(
                "placements",
                queryset=available_placements(project),
                to_attr="visible_placements",
            )
        )
        .order_by("position", "id")
    )


def next_position(query):
    return (query.aggregate(last=Max("position"))["last"] or 0) + 1


def reorder(query, obj, direction):
    objects = list(query)
    index = next((i for i, item in enumerate(objects) if item.pk == obj.pk), None)
    if index is None:
        return
    other = index + (-1 if direction == "up" else 1)
    if not 0 <= other < len(objects):
        return
    objects[index], objects[other] = objects[other], objects[index]
    for position, item in enumerate(objects):
        item.position = position
    query.model.objects.bulk_update(objects, ["position"])


def add_excerpts(group, excerpts):
    position = next_position(group.placements.all())
    for excerpt in excerpts:
        placement, created = ResearchPlacement.objects.get_or_create(
            group=group, excerpt=excerpt, defaults={"position": position}
        )
        if created:
            position += 1
        elif placement.is_archived:
            placement.is_archived = False
            placement.position = position
            placement.save(update_fields=["is_archived", "position"])
            position += 1


def export_outline_markdown(project, groups, generated_at):
    yield f"# {markdown_text(' '.join(project.name.splitlines()))} · 材料提纲\n\n源笺 · 课题材料编排\n\n生成时间：{generated_at}\n\n"
    for group_index, group in enumerate(groups, start=1):
        yield f"## {group_index}. {markdown_text(' '.join(group.name.splitlines()))}\n\n"
        if group.description:
            yield (
                "\n".join(
                    "> " + markdown_text(line)
                    for line in group.description.splitlines()
                )
                + "\n\n"
            )
        for excerpt_index, placement in enumerate(group.visible_placements, start=1):
            excerpt = placement.excerpt
            bookmark = excerpt.bookmark
            safe_url = quote(bookmark.url, safe=":/?=&%#@+~,;!$-_.")
            yield f"### {group_index}.{excerpt_index} {markdown_text(' '.join(bookmark.resolved_title.splitlines()))}\n\n"
            yield f"原始来源：[打开资料](<{safe_url}>)\n\n来源位置：{markdown_text(' '.join(excerpt.locator.splitlines()))}\n\n"
            yield (
                "原文摘录：\n\n"
                + "\n".join(
                    "> " + markdown_text(line)
                    for line in excerpt.original_text.splitlines()
                )
                + "\n\n"
            )
            yield (
                "我的理解：\n\n"
                + (
                    "\n".join(
                        "> " + markdown_text(line)
                        for line in excerpt.interpretation.splitlines()
                    )
                    if excerpt.interpretation
                    else "尚未记录。"
                )
                + "\n\n"
            )
        if not group.visible_placements:
            yield "此分组还没有可用的摘录。\n\n"
        unavailable = group.saved_count - len(group.visible_placements)
        if unavailable:
            yield f"{unavailable} 条编排材料暂不可用，未导出内容。\n\n"
        yield "---\n\n"
