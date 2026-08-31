import html
from io import BytesIO

import requests
from PIL import Image


class TelegramBot:
    API = "https://api.telegram.org/bot{token}/{method}"
    CAPTION_LIMIT = 1024
    MESSAGE_LIMIT = 4096

    def __init__(self, token: str, channel_id: str):
        self.token = token
        self.channel_id = channel_id
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/140.0 Safari/537.36"
                )
            }
        )

    def _call(self, method: str, files=None, **kwargs):
        url = self.API.format(token=self.token, method=method)
        r = self.session.post(url, data=kwargs, files=files, timeout=60)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data}")
        return data["result"]

    def _prepare_photo(self, image_url: str, referer: str) -> BytesIO | None:
        try:
            r = self.session.get(
                image_url,
                timeout=25,
                headers={"Referer": referer, "Accept": "image/*,*/*;q=0.8"},
            )
            r.raise_for_status()
        except requests.RequestException:
            return None

        raw = r.content
        if not raw or len(raw) < 100:
            return None

        try:
            img = Image.open(BytesIO(raw))
            if img.mode != "RGB":
                img = img.convert("RGB")
            out = BytesIO()
            img.save(out, format="JPEG", quality=88, optimize=True)
            out.seek(0)
            out.name = "photo.jpg"
            return out
        except Exception:
            return None

    def _build_caption(
        self,
        title: str,
        text: str,
        url: str,
        add_source_link: bool,
        limit: int,
    ) -> str:
        title_html = f"<b>📰 {html.escape(title)}</b>"
        source = (
            f'\n\n🔗 <a href="{html.escape(url, quote=True)}">Источник</a>'
            if add_source_link
            else ""
        )
        overhead = len(title_html) + len(source) + (2 if text else 0)
        budget = max(0, limit - overhead)

        body = html.escape(text.strip())
        if budget and len(body) > budget:
            cut = body[: max(0, budget - 1)].rsplit(" ", 1)
            body = (cut[0] if cut and cut[0] else body[: budget - 1]).rstrip() + "…"
        elif not budget:
            body = ""

        parts = [title_html]
        if body:
            parts.append(body)
        caption = "\n\n".join(parts) + source
        return caption[:limit]

    def send_news(
        self,
        title: str,
        text: str,
        url: str,
        image_url: str | None = None,
        add_source_link: bool = True,
        max_chars: int = 0,
    ):
        title = title.strip()
        text = text.strip()

        if max_chars and len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0].rstrip() + "…"

        photo = self._prepare_photo(image_url, url) if image_url else None

        if photo:
            caption = self._build_caption(
                title, text, url, add_source_link, self.CAPTION_LIMIT
            )
            try:
                self._call(
                    "sendPhoto",
                    files={"photo": ("photo.jpg", photo, "image/jpeg")},
                    chat_id=self.channel_id,
                    caption=caption,
                    parse_mode="HTML",
                )
                return
            except Exception:
                photo = None

        message = self._build_caption(
            title, text, url, add_source_link, self.MESSAGE_LIMIT
        )
        self._call(
            "sendMessage",
            chat_id=self.channel_id,
            text=message,
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
