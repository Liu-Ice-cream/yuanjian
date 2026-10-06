from django import forms
from django.core import signing

from bookmarks.widgets import FormInput, FormSelect, FormTextarea

from .models import ResearchPaper
from .paper_services import normalize_doi

PREVIEW_SALT = "research.paper-preview.v1"


def read_preview(token, user, bookmark, doi):
    try:
        payload = signing.loads(token, salt=PREVIEW_SALT, max_age=3600)
        if (
            payload["owner"] != user.pk
            or payload["bookmark"] != bookmark.pk
            or payload["metadata"]["doi"] != doi
        ):
            raise ValueError("Mismatched preview")
        return payload["metadata"]
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        raise forms.ValidationError(
            "DOI 已更改或预览已失效，请重新读取，或取消候选信息后手动保存。"
        ) from None


class PaperForm(forms.ModelForm):
    lookup_token = forms.CharField(
        required=False, max_length=120000, widget=forms.HiddenInput()
    )

    class Meta:
        model = ResearchPaper
        fields = ["doi", "title", "authors", "year", "venue", "entry_type"]
        widgets = {
            "doi": FormInput(),
            "title": FormInput(),
            "authors": FormTextarea(attrs={"rows": 5}),
            "year": FormInput(attrs={"type": "number", "min": 1000, "max": 9999}),
            "venue": FormInput(),
            "entry_type": FormSelect(),
        }
        help_texts = {
            "doi": "可粘贴 DOI 或 doi.org 链接；没有 DOI 也可手动记录。",
            "authors": "每行一位作者，推荐“姓, 名”，顺序与论文一致。",
            "title": "填写真实论文标题；留空时不导出此条引用。",
        }

    def __init__(self, user, bookmark, *args, **kwargs):
        self.user = user
        self.bookmark = bookmark
        self.duplicate = None
        super().__init__(*args, **kwargs)
        self.instance.owner = user
        self.instance.bookmark = bookmark

    def clean_doi(self):
        doi = normalize_doi(self.cleaned_data["doi"])
        if doi:
            existing = (
                ResearchPaper.objects.filter(owner=self.user, doi=doi)
                .exclude(bookmark=self.bookmark)
                .select_related("bookmark")
                .first()
            )
            if existing:
                self.duplicate = existing.bookmark
                raise forms.ValidationError(
                    "同一 DOI 的论文已存在，请打开已有资料，避免重复记录。"
                )
        return doi

    def clean_lookup_token(self):
        token = self.cleaned_data["lookup_token"]
        if token and "doi" in self.cleaned_data:
            read_preview(token, self.user, self.bookmark, self.cleaned_data["doi"])
        return token
