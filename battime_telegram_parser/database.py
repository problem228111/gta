import sqlite3
from pathlib import Path


class Database:
    def __init__(self, path: str = "news.db"):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self):
        return sqlite3.connect(self.path)

    def _init(self):
        with self._connect() as con:
            con.execute(
                '''
                CREATE TABLE IF NOT EXISTS news (
                    url TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    sent_at TEXT NOT NULL
                )
                '''
            )
            con.commit()

    def exists(self, url: str) -> bool:
        with self._connect() as con:
            row = con.execute(
                "SELECT 1 FROM news WHERE url = ? LIMIT 1", (url,)
            ).fetchone()
            return row is not None

    def save(self, url: str, title: str, sent_at: str):
        with self._connect() as con:
            con.execute(
                "INSERT OR IGNORE INTO news(url, title, sent_at) VALUES (?, ?, ?)",
                (url, title, sent_at),
            )
            con.commit()
