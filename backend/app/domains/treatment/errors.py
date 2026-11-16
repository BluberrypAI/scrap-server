class TreatmentError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def cursor_error(code="invalid-cursor"):
    if code == "stale-cursor":
        return TreatmentError(code, "명부가 갱신됐어요. 첫 페이지부터 다시 조회해 주세요.")
    return TreatmentError(code, "조회 조건이 바뀌었거나 커서가 유효하지 않아요.")
