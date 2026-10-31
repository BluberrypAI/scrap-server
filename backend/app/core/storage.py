"""업로드 파일 저장소.

지금은 로컬 폴더(UPLOAD_DIR)에 저장함. Blob Storage로 바꿀 때는 같은 메서드를 가진 클래스를
만들고 get_storage만 바꿈.
"""

from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings


class LocalFileStorage:
    def __init__(self, root: str):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        # key는 서버가 만든 값이지만, 경로 이탈은 막아 둠
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("잘못된 저장 키")
        return path

    def save(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


@lru_cache
def get_storage() -> LocalFileStorage:
    return LocalFileStorage(get_settings().upload_dir)
