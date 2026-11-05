"""Google Drive e respostas HTTP simulados, para testar sem rede."""


class Exec:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeDrive:
    """Google Drive em memória: {id: {name, mimeType, parents}}."""
    FOLDER = "application/vnd.google-apps.folder"

    def __init__(self):
        self.items, self.n = {}, 0

    def add(self, name, parent, mime="text/plain", props=None, modified="2026-01-01T00:00:00Z"):
        self.n += 1
        item_id = f"id{self.n}"
        self.items[item_id] = {
            "name": name, "mimeType": mime, "parents": [parent], "appProperties": props or {}, "modifiedTime": modified,
        }
        return item_id

    def files(self):
        return self

    def list(self, q, **kw):
        parent = q.split("'")[1]
        want_folders = "mimeType = '" in q and "!=" not in q
        found = [
            {**v, "id": k} for k, v in self.items.items()
            if parent in v["parents"] and (v["mimeType"] == self.FOLDER) == want_folders
        ]
        return Exec({"files": found})

    def create(self, body, **kw):
        return Exec({"id": self.add(
            body["name"], body["parents"][0], body.get("mimeType", "video/mp4"), body.get("appProperties"),
        )})

    def get_media(self, **kw):
        return object()


class FakeDownloader:
    def __init__(self, fh, request):
        self.fh = fh

    def next_chunk(self):
        self.fh.write(b"Ola equipe.")
        return None, True


class FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_bytes(self, n):
        yield b"fake-mp4-bytes"


class FakeUpstream:
    """Resposta do Drive simulada (mesma interface usada do httpx)."""
    def __init__(self, status=200, body=b"0123456789", headers=None):
        self.status_code, self.body = status, body
        self.headers = headers or {"Content-Length": str(len(body))}
        self.closed = False

    def iter_bytes(self, n):
        yield self.body

    def close(self):
        self.closed = True


class FakeClient:
    closed = False

    def close(self):
        self.closed = True
