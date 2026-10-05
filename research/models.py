from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from bookmarks.models import Bookmark


class ResearchProject(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField("课题名称", max_length=120)
    description = models.TextField("研究目标", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name"], name="unique_research_project_per_owner"
            )
        ]

    def __str__(self):
        return self.name


class ResearchItem(models.Model):
    class MaterialType(models.TextChoices):
        PAPER = "paper", "论文"
        CODE = "code", "代码仓库"
        DATASET = "dataset", "数据集"
        ARTICLE = "article", "技术文章"
        OTHER = "other", "其他资料"

    class ReadingStage(models.TextChoices):
        COLLECTED = "collected", "待阅读"
        READING = "reading", "阅读中"
        REVIEWED = "reviewed", "已阅读"
        USED = "used", "已复用"

    bookmark = models.OneToOneField(
        Bookmark, on_delete=models.CASCADE, related_name="research_item"
    )
    project = models.ForeignKey(
        ResearchProject,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="items",
        verbose_name="所属课题",
    )
    material_type = models.CharField(
        "资料类型",
        max_length=16,
        choices=MaterialType.choices,
        default=MaterialType.OTHER,
    )
    reading_stage = models.CharField(
        "阅读阶段",
        max_length=16,
        choices=ReadingStage.choices,
        default=ReadingStage.COLLECTED,
    )
    question = models.TextField("研究问题", blank=True)
    conclusion = models.TextField("核心结论", blank=True)
    evidence = models.TextField("证据与实验", blank=True)
    limitations = models.TextField("局限与注意事项", blank=True)
    relevance = models.TextField("与课题的关系", blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if (
            self.project_id
            and self.bookmark_id
            and self.project.owner_id != self.bookmark.owner_id
        ):
            raise ValidationError({"project": "只能将资料归入自己的课题。"})

    @property
    def has_research_record(self):
        return bool(self.question.strip() or self.conclusion.strip())

    @property
    def effective_stage(self):
        # Existing clients still update Bookmark.unread. Respect those updates
        # without changing the upstream model or adding queries to every save.
        if self.bookmark.unread:
            return (
                self.ReadingStage.READING
                if self.reading_stage == self.ReadingStage.READING
                else self.ReadingStage.COLLECTED
            )
        return (
            self.ReadingStage.USED
            if self.reading_stage == self.ReadingStage.USED
            else self.ReadingStage.REVIEWED
        )

    @property
    def stage_label(self):
        return self.ReadingStage(self.effective_stage).label


class ResearchExcerpt(models.Model):
    bookmark = models.ForeignKey(
        Bookmark, on_delete=models.CASCADE, related_name="research_excerpts"
    )
    original_text = models.TextField("原文摘录", max_length=20000)
    interpretation = models.TextField("我的理解", max_length=20000, blank=True)
    locator = models.CharField("来源位置", max_length=240)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.original_text[:80]
