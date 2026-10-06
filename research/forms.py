import re

from django import forms
from django.core.exceptions import PermissionDenied
from django.core.validators import URLValidator
from django.db import transaction

from bookmarks.models import Bookmark, build_tag_string
from bookmarks.services.bookmarks import create_bookmark, update_bookmark
from bookmarks.widgets import FormInput, FormSelect, FormTextarea

from .models import (
    ResearchExcerpt,
    ResearchGroup,
    ResearchItem,
    ResearchPaper,
    ResearchProject,
)
from .paper_services import normalize_doi


class GroupForm(forms.ModelForm):
    class Meta:
        model = ResearchGroup
        fields = ["name", "description"]
        widgets = {"name": FormInput(), "description": FormTextarea(attrs={"rows": 3})}
        error_messages = {"name": {"required": "请填写分组名称。"}}

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if (
            ResearchGroup.objects.filter(project=self.instance.project, name=name)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise forms.ValidationError("已有同名分组；若已移除，可先恢复该分组。")
        return name


class OrderForm(forms.Form):
    direction = forms.ChoiceField(choices=[("up", "上移"), ("down", "下移")])


class PlacementMoveForm(forms.Form):
    target = forms.ModelChoiceField(
        label="目标分组",
        queryset=ResearchGroup.objects.none(),
        widget=FormSelect(),
        error_messages={
            "required": "请选择目标分组。",
            "invalid_choice": "请选择当前课题中的有效分组。",
        },
    )

    def __init__(self, group, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target"].queryset = ResearchGroup.objects.filter(
            project=group.project, is_archived=False
        ).exclude(pk=group.pk)


class ExcerptForm(forms.ModelForm):
    class Meta:
        model = ResearchExcerpt
        fields = ["original_text", "interpretation", "locator"]
        widgets = {
            "original_text": FormTextarea(attrs={"rows": 6}),
            "interpretation": FormTextarea(attrs={"rows": 4}),
            "locator": FormInput(
                attrs={"placeholder": "例如：第 5 页、表 2、Methods 章节"}
            ),
        }
        help_texts = {
            "original_text": "粘贴原文内容，保留原意和表述。",
            "interpretation": "记录你对这段内容的理解或准备怎样使用，可稍后补充。",
            "locator": "填写页码、章节、图表编号或网页段落，方便回到原文核对。",
        }
        error_messages = {
            "original_text": {"required": "请填写原文摘录。"},
            "locator": {"required": "请填写来源位置，方便以后核对。"},
        }


class ExcerptSelectionField(forms.ModelMultipleChoiceField):
    def _check_values(self, value):
        # ResearchExcerpt uses a 32-bit AutoField. Validate before SQL's IN
        # lookup, which can overflow SQLite when given an arbitrary integer.
        for pk in value:
            try:
                valid = 0 < int(pk) <= 2147483647
            except (ValueError, TypeError):
                valid = False
            if not valid:
                raise forms.ValidationError(
                    self.error_messages["invalid_pk_value"],
                    code="invalid_pk_value",
                    params={"pk": pk},
                )
        return super()._check_values(value)


class ExcerptSelectionForm(forms.Form):
    selected = ExcerptSelectionField(
        queryset=ResearchExcerpt.objects.none(),
        error_messages={
            "required": "请先勾选需要导出的摘录。",
            "invalid_choice": "所选摘录不在当前范围内，请重新选择。",
            "invalid_pk_value": "所选摘录无效，请重新选择。",
        },
    )

    def __init__(self, queryset, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["selected"].queryset = queryset


class MetadataLookupForm(forms.Form):
    url = forms.URLField(
        max_length=2048,
        validators=[URLValidator(schemes=["http", "https"])],
        error_messages={
            "required": "请先填写原始链接。",
            "invalid": "请输入有效的 HTTP 或 HTTPS 链接。",
        },
    )


class ProjectForm(forms.ModelForm):
    class Meta:
        model = ResearchProject
        fields = ["name", "description"]
        widgets = {"name": FormInput(), "description": FormTextarea(attrs={"rows": 4})}

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("请填写课题名称。")
        existing = ResearchProject.objects.filter(owner=self.user, name=name)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise forms.ValidationError("已有同名课题，请使用不同名称。")
        return name

    def save(self, commit=True):
        if self.instance.pk and self.instance.owner_id != self.user.pk:
            raise PermissionDenied
        project = super().save(commit=False)
        project.owner = self.user
        if commit:
            project.save()
        return project


class MaterialForm(forms.ModelForm):
    doi = forms.CharField(
        label="论文 DOI（可选）",
        max_length=512,
        required=False,
        widget=FormInput(),
        help_text="用于提醒相同论文；保存后可读取作者、年份和出版信息。",
    )
    tags = forms.CharField(
        label="标签",
        required=False,
        max_length=2048,
        widget=FormInput(),
        help_text="多个标签用空格分隔。",
    )
    project = forms.ModelChoiceField(
        label="所属课题",
        queryset=ResearchProject.objects.none(),
        required=False,
        empty_label="暂不归入课题",
        widget=FormSelect(),
    )
    material_type = forms.ChoiceField(
        label="资料类型", choices=ResearchItem.MaterialType.choices, widget=FormSelect()
    )
    reading_stage = forms.ChoiceField(
        label="阅读阶段", choices=ResearchItem.ReadingStage.choices, widget=FormSelect()
    )
    question = forms.CharField(
        label="研究问题",
        required=False,
        max_length=20000,
        widget=FormTextarea(
            attrs={"rows": 3, "placeholder": "这条资料试图解决什么问题？"}
        ),
    )
    conclusion = forms.CharField(
        label="核心结论",
        required=False,
        max_length=20000,
        widget=FormTextarea(attrs={"rows": 3, "placeholder": "你确认了哪些结论？"}),
    )
    evidence = forms.CharField(
        label="证据与实验",
        required=False,
        max_length=20000,
        widget=FormTextarea(
            attrs={"rows": 3, "placeholder": "记录数据、实验结果或原文位置。"}
        ),
    )
    limitations = forms.CharField(
        label="局限与注意事项",
        required=False,
        max_length=20000,
        widget=FormTextarea(
            attrs={"rows": 3, "placeholder": "哪些条件下不适用？还有哪些问题？"}
        ),
    )
    relevance = forms.CharField(
        label="与课题的关系",
        required=False,
        max_length=20000,
        widget=FormTextarea(
            attrs={"rows": 3, "placeholder": "准备在你的研究、汇报或写作中怎样使用？"}
        ),
    )
    card_fields = ("question", "conclusion", "evidence", "limitations", "relevance")

    class Meta:
        model = Bookmark
        fields = ["url", "title", "description", "notes"]
        labels = {
            "url": "原始链接",
            "title": "资料标题",
            "description": "简要介绍",
            "notes": "补充笔记",
        }
        widgets = {
            "url": FormInput(attrs={"type": "url", "autofocus": True}),
            "title": FormInput(),
            "description": FormTextarea(attrs={"rows": 3}),
            "notes": FormTextarea(attrs={"rows": 5}),
        }

    def __init__(self, user, *args, **kwargs):
        self.user = user
        self.duplicate_bookmark = None
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = ResearchProject.objects.filter(owner=user)
        if self.instance.pk:
            self.fields.pop("doi")
        item = (
            getattr(self.instance, "research_item", None) if self.instance.pk else None
        )
        self.initial.update(
            {
                "tags": " ".join(self.instance.tag_names) if self.instance.pk else "",
                "material_type": ResearchItem.MaterialType.OTHER,
                "reading_stage": ResearchItem.ReadingStage.COLLECTED
                if not self.instance.pk or self.instance.unread
                else ResearchItem.ReadingStage.REVIEWED,
            }
        )
        if item:
            self.initial.update(
                {
                    "project": item.project_id,
                    "material_type": item.material_type,
                    "reading_stage": item.effective_stage,
                    **{name: getattr(item, name) for name in self.card_fields},
                }
            )

    def clean_doi(self):
        doi = normalize_doi(self.cleaned_data["doi"])
        if doi:
            existing = (
                ResearchPaper.objects.filter(owner=self.user, doi=doi)
                .select_related("bookmark")
                .first()
            )
            if existing:
                self.duplicate_bookmark = existing.bookmark
                raise forms.ValidationError("同一 DOI 的论文已存在，请打开已有资料。")
        return doi

    def clean_url(self):
        url = self.cleaned_data["url"]
        existing = Bookmark.query_existing(self.user, url)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        self.duplicate_bookmark = existing.first()
        if self.duplicate_bookmark:
            raise forms.ValidationError(
                "资料已存在。请打开已有资料编辑，避免覆盖研究记录。"
            )
        return url

    @transaction.atomic
    def save(self, commit=True):
        if not commit:
            raise ValueError(
                "MaterialForm saves the bookmark and research card together."
            )
        if self.instance.pk and self.instance.owner_id != self.user.pk:
            raise PermissionDenied
        bookmark = super().save(commit=False)
        stage = self.cleaned_data["reading_stage"]
        bookmark.unread = stage in (
            ResearchItem.ReadingStage.COLLECTED,
            ResearchItem.ReadingStage.READING,
        )
        tags = build_tag_string(re.split(r"\s+", self.cleaned_data["tags"].strip()))
        bookmark = (
            update_bookmark(bookmark, tags, self.user)
            if bookmark.pk
            else create_bookmark(bookmark, tags, self.user)
        )
        item, _ = ResearchItem.objects.get_or_create(bookmark=bookmark)
        for field in ("project", "material_type", "reading_stage", *self.card_fields):
            setattr(item, field, self.cleaned_data[field])
        item.full_clean()
        item.save()
        if self.cleaned_data.get("doi"):
            ResearchPaper.objects.create(
                bookmark=bookmark, owner=self.user, doi=self.cleaned_data["doi"]
            )
        return bookmark
