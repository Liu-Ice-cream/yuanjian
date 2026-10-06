import json
import re
from time import monotonic
from urllib.parse import quote, unquote, urlsplit

from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError

from bookmarks.services import http_client


def normalize_doi(value):
    value = value.strip()
    if not value:
        return ""
    if value.lower().startswith(("http://", "https://")):
        try:
            parsed = urlsplit(value)
        except ValueError:
            raise ValidationError("请输入有效的 DOI 或 doi.org 链接。") from None
        if parsed.netloc.lower() not in ("doi.org", "www.doi.org", "dx.doi.org"):
            raise ValidationError("请输入 DOI 或 doi.org 链接。")
        value = unquote(parsed.path.lstrip("/"))
    elif value.lower().startswith("doi:"):
        value = value[4:].strip()
    if (
        len(value) > 512
        or not re.fullmatch(r"10\.\d{4,9}/[^\s<>]+", value)
        or any(ord(c) < 32 for c in value)
    ):
        raise ValidationError("DOI 格式无效，例如：10.1038/nature14539。")
    return value.lower()


def clean_metadata_text(value, limit):
    if not isinstance(value, str):
        return ""
    return " ".join(BeautifulSoup(value, "html.parser").get_text(" ").split())[:limit]


def parse_crossref(message, doi):
    if not isinstance(message, dict) or normalize_doi(message.get("DOI", "")) != doi:
        raise ValueError("Mismatched DOI metadata")
    title_values = message.get("title") or []
    venues = message.get("container-title") or []
    title = (
        clean_metadata_text(title_values[0], 1000)
        if isinstance(title_values, list) and title_values
        else ""
    )
    venue = (
        clean_metadata_text(venues[0], 1000)
        if isinstance(venues, list) and venues
        else ""
    )
    authors = []
    for author in message.get("author") or []:
        if not isinstance(author, dict):
            continue
        family = clean_metadata_text(author.get("family"), 240)
        given = clean_metadata_text(author.get("given"), 240)
        name = ", ".join(
            part for part in [family, given] if part
        ) or clean_metadata_text(author.get("name"), 480)
        if name:
            authors.append(name)
    authors_text = "\n".join(authors)
    if len(authors_text) > 20000:
        raise ValueError("Too many authors")
    year = None
    # Publication dates describe publication; created/indexed dates do not.
    for field in ("published", "published-print", "published-online", "issued"):
        dates = message.get(field)
        parts = dates.get("date-parts") if isinstance(dates, dict) else None
        if (
            isinstance(parts, list)
            and parts
            and isinstance(parts[0], list)
            and parts[0]
        ):
            value = parts[0][0]
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 1000 <= value <= 9999
            ):
                year = value
                break
    entry_type = {
        "journal-article": "article",
        "proceedings-article": "inproceedings",
    }.get(message.get("type"), "misc")
    if not title:
        raise ValueError("Missing title")
    return {
        "doi": doi,
        "title": title,
        "authors": authors_text,
        "year": str(year) if year else "",
        "venue": venue,
        "entry_type": entry_type,
    }


def lookup_crossref(doi):
    try:
        started = monotonic()
        url = "https://api.crossref.org/works/" + quote(doi, safe="")
        with http_client.get(
            url,
            timeout=(4, 10),
            stream=True,
            trust_env=False,
            allow_redirects=False,
            headers={
                "Accept": "application/json",
                "User-Agent": "Yuanjian/0.1.4 (https://github.com/Liu-Ice-cream/yuanjian)",
            },
        ) as response:
            if response.status_code != 200:
                return None
            data = bytearray()
            for chunk in response.iter_content(chunk_size=16384):
                if monotonic() - started > 15 or len(data) + len(chunk) > 1024 * 1024:
                    return None
                data.extend(chunk)
            payload = json.loads(data)
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                return None
            return parse_crossref(payload.get("message"), doi)
    except (
        http_client.RequestException,
        ValueError,
        TypeError,
        AttributeError,
        ValidationError,
    ):
        return None


def bibtex_text(value):
    translations = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "%": r"\%",
        "&": r"\&",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(translations.get(c, c) for c in " ".join(str(value).split()))


def export_bibtex(papers):
    yield "% 源笺 · 论文引用。UTF-8 编码；引用信息缺失时请按提示核对。\n\n"
    for paper in papers:
        if not paper.title.strip():
            continue
        fields = [("title", "{" + bibtex_text(paper.title) + "}")]
        authors = []
        for line in paper.authors.splitlines():
            if line.strip():
                author = bibtex_text(line)
                if re.search(r"\band\b", line, re.I):
                    author = "{" + author + "}"
                authors.append(author)
        if authors:
            fields.append(("author", " and ".join(authors)))
        if paper.year:
            fields.append(("year", str(paper.year)))
        if paper.venue:
            fields.append(
                (
                    "journal"
                    if paper.entry_type == "article"
                    else "booktitle"
                    if paper.entry_type == "inproceedings"
                    else "howpublished",
                    bibtex_text(paper.venue),
                )
            )
        if paper.doi:
            fields.append(("doi", quote(paper.doi, safe="/:?=&%#@+~,;!$-_.()*[]")))
        # Identifier fields use URI encoding, rather than LaTeX escaping.
        # Importers must receive usable DOI/URL values, including underscores.
        fields.append(("url", quote(paper.bookmark.url, safe=":/?=&%#@+~,;!$-_.()*[]")))
        if paper.missing_fields:
            fields.append(
                (
                    "note",
                    bibtex_text(
                        "源笺提示：缺少"
                        + "、".join(paper.missing_fields)
                        + "，请核对后补充。"
                    ),
                )
            )
        yield f"@{paper.entry_type}{{{paper.citation_key},\n"
        yield (
            ",\n".join(f"  {name} = {{{value}}}" for name, value in fields) + "\n}\n\n"
        )
