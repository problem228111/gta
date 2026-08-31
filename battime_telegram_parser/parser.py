import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo


DATE_RE = re.compile(
    r"(?P<date>\d{1,2}-\d{1,2}-\d{4}),\s*(?P<time>\d{1,2}:\d{2})"
)
TIME_RE = re.compile(r"\b(?P<time>\d{1,2}:\d{2})\b")


@dataclass
class NewsItem:
    title: str
    url: str
    published_at: datetime | None = None


@dataclass
class Article:
    title: str
    url: str
    text: str
    image_url: str | None
    published_at: datetime | None = None


class BattimeParser:
    def __init__(self, base_url="https://battime.ru/", timezone="Europe/Moscow"):
        self.base_url = base_url.rstrip("/") + "/"
        self.tz = ZoneInfo(timezone)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/140.0 Safari/537.36"
                ),
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            }
        )

    def fetch(self, url: str) -> BeautifulSoup:
        r = self.session.get(url, timeout=25)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or r.encoding
        return BeautifulSoup(r.text, "lxml")

    def _is_article_url(self, href: str) -> bool:
        if not href:
            return False
        full = urljoin(self.base_url, href)
        p = urlparse(full)
        if p.netloc and p.netloc != urlparse(self.base_url).netloc:
            return False
        path = p.path.lower()
        if not path.endswith(".html"):
            return False
        if any(x in path for x in ("/page/", "/search/", "/tags/", "/user/")):
            return False
        return True

    def _parse_datetime(self, text: str) -> datetime | None:
        text = " ".join(text.split())
        m = DATE_RE.search(text)
        if m:
            try:
                return datetime.strptime(
                    f"{m.group('date')} {m.group('time')}",
                    "%d-%m-%Y %H:%M",
                ).replace(tzinfo=self.tz)
            except ValueError:
                pass

        now = datetime.now(self.tz)

        # На сайте встречаются "Сегодня, 14:12" и "Вчера, 22:06".
        m = re.search(r"Сегодня,\s*(\d{1,2}:\d{2})", text, re.I)
        if m:
            hh, mm = map(int, m.group(1).split(":"))
            return now.replace(hour=hh, minute=mm, second=0, microsecond=0)

        m = re.search(r"Вчера,\s*(\d{1,2}:\d{2})", text, re.I)
        if m:
            hh, mm = map(int, m.group(1).split(":"))
            d = now - timedelta(days=1)
            return d.replace(hour=hh, minute=mm, second=0, microsecond=0)

        return None

    def _candidate_date(self, anchor) -> datetime | None:
        # Ищем дату в ближайших родителях. Это устойчивее, чем
        # привязываться к конкретному div-классу сайта.
        node = anchor
        for _ in range(7):
            if node is None:
                break
            dt = self._parse_datetime(node.get_text(" ", strip=True))
            if dt:
                return dt
            node = node.parent
        return None

    def get_news_list(self, rostov_only=True, keywords=None) -> list[NewsItem]:
        soup = self.fetch(self.base_url)
        keywords = [x.strip().lower() for x in (keywords or []) if x.strip()]

        candidates = []
        seen = set()

        for a in soup.select("a[href]"):
            href = a.get("href")
            if not self._is_article_url(href):
                continue

            title = a.get_text(" ", strip=True)
            if len(title) < 10 or len(title) > 500:
                continue

            url = urljoin(self.base_url, href)
            if url in seen:
                continue
            seen.add(url)

            dt = self._candidate_date(a)
            if dt is None:
                continue

            haystack = title.lower()

            # Если фильтр включён, сначала проверяем заголовок.
            # При отсутствии совпадения проверяем краткий текст блока.
            if rostov_only and keywords:
                context = ""
                parent = a.parent
                for _ in range(3):
                    if parent is None:
                        break
                    context += " " + parent.get_text(" ", strip=True)
                    parent = parent.parent
                context = (haystack + " " + context).lower()

                if not any(k in context for k in keywords):
                    continue

            candidates.append(NewsItem(title=title, url=url, published_at=dt))

        candidates.sort(
            key=lambda x: x.published_at or datetime.min.replace(tzinfo=self.tz),
            reverse=True,
        )
        return candidates

    def get_latest_news(self, rostov_only=True, keywords=None) -> NewsItem | None:
        items = self.get_news_list(rostov_only=rostov_only, keywords=keywords)
        return items[0] if items else None

    @staticmethod
    def _clean_text(container) -> str:
        # Убираем элементы, которые почти наверняка не являются текстом статьи.
        for bad in container.select(
            "script, style, noscript, iframe, form, nav, footer, "
            ".social, .share, .comments, .comment, .related, .advert, "
            ".ads, .banner, .breadcrumbs"
        ):
            bad.decompose()

        paragraphs = []
        for p in container.select("p"):
            txt = " ".join(p.get_text(" ", strip=True).split())
            if len(txt) >= 20:
                paragraphs.append(txt)

        # Если p нет, используем весь текст контейнера.
        if not paragraphs:
            txt = " ".join(container.get_text(" ", strip=True).split())
            return txt

        # Удаляем подряд идущие дубликаты.
        out = []
        for p in paragraphs:
            if not out or p != out[-1]:
                out.append(p)

        return "\n\n".join(out)

    def _find_article_container(self, soup):
        h1 = soup.find("h1")
        if not h1:
            return None

        # Сначала пробуем распространённые варианты.
        selectors = [
            ".full-text",
            ".fullstory",
            ".article-text",
            ".article-content",
            ".news-text",
            ".news-content",
            ".entry-content",
            ".content",
            "article",
            "main",
        ]

        scored = []
        for selector in selectors:
            for node in soup.select(selector):
                text = self._clean_text(BeautifulSoup(str(node), "lxml"))
                if len(text) >= 200:
                    score = min(len(text), 10000) + len(node.select("p")) * 200
                    scored.append((score, node))

        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            return scored[0][1]

        # Универсальный fallback: поднимаемся от h1 и ищем блок,
        # в котором много абзацев.
        node = h1.parent
        for _ in range(8):
            if node is None:
                break
            if len(node.select("p")) >= 2:
                return node
            node = node.parent

        return h1.parent

    def _find_image_url(self, soup, page_url: str) -> str | None:
        meta = soup.find("meta", attrs={"property": "og:image"})
        if meta and meta.get("content"):
            return urljoin(page_url, meta["content"].strip())

        container = self._find_article_container(soup) or soup
        for img in container.select("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-original")
            if not src:
                continue
            classes = " ".join(img.get("class") or []).lower()
            if "prev" in classes or "logo" in classes:
                continue
            full = urljoin(page_url, src.strip())
            path = urlparse(full).path.lower()
            if "/templates/" in path:
                continue
            if any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")):
                return full
        return None

    def get_article(self, item: NewsItem) -> Article:
        soup = self.fetch(item.url)

        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else item.title

        # Для картинки это самый надёжный вариант: большинство страниц
        # отдают главное фото через og:image.
        image_url = self._find_image_url(soup, item.url)

        container = self._find_article_container(soup)
        text = self._clean_text(container) if container else ""

        # Если контейнер случайно включил заголовок, убираем его.
        text = re.sub(
            rf"^\s*{re.escape(title)}\s*",
            "",
            text,
            flags=re.I,
        ).strip()

        return Article(
            title=title,
            url=item.url,
            text=text,
            image_url=image_url,
            published_at=item.published_at,
        )
