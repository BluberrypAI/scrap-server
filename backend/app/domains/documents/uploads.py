"""업로드 파일 검사. 문서·추가 자료 업로드가 함께 씀."""

from fastapi import UploadFile, status

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.domains.documents import service


async def read_upload(file: UploadFile) -> tuple[str, bytes]:
    """형식과 크기를 검사하고 (파일 이름, 내용)을 돌려줌."""
    file_name = file.filename or ""
    try:
        service.file_format(file_name)
    except service.FileTypeUnsupportedError:
        raise AppError(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            ErrorCode.FILE_TYPE_UNSUPPORTED,
            f"지원 형식: {', '.join(sorted(set(service.ALLOWED_FORMATS.values())))}",
        ) from None
    limit = get_settings().max_upload_mb * 1024 * 1024
    # 한도보다 1바이트 더 읽어 초과 여부만 확인함 (큰 파일을 전부 메모리에 올리지 않음)
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise AppError(
            status.HTTP_413_CONTENT_TOO_LARGE,
            ErrorCode.FILE_TOO_LARGE,
            f"파일은 {get_settings().max_upload_mb}MB 이하여야 함",
        )
    return file_name, data
