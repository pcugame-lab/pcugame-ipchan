"""
유틸리티 모듈.
로깅 설정, 시간 변환, 민감정보 마스킹 등을 담당한다.
"""

import logging
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

SEOUL_TZ = ZoneInfo("Asia/Seoul")

# Discord 토큰 패턴: Header.Payload.Signature 형태
_TOKEN_PATTERN = re.compile(
    r"[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{27,}"
)


def mask_token(text: str) -> str:
    """Discord 토큰처럼 보이는 문자열을 마스킹한다."""
    return _TOKEN_PATTERN.sub("[TOKEN_MASKED]", text)


class TokenMaskingFilter(logging.Filter):
    """로그 레코드에서 Discord 토큰을 자동으로 마스킹하는 필터."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            try:
                record.msg = mask_token(record.msg % record.args)
            except Exception:
                record.msg = mask_token(str(record.msg))
            record.args = ()
        else:
            record.msg = mask_token(str(record.msg))
        return True


def setup_logging() -> None:
    """
    애플리케이션 로깅을 설정한다. 콘솔 + 파일 핸들러, 토큰 마스킹 필터 적용.
    파일 핸들러 생성에 실패하면(볼륨 권한 문제 등) 콘솔 출력만으로 graceful fallback한다.
    """
    os.makedirs("logs", exist_ok=True)

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    mask_filter = TokenMaskingFilter()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    console_handler.addFilter(mask_filter)

    handlers: list[logging.Handler] = [console_handler]
    file_logging_ok = False

    try:
        file_handler = logging.FileHandler("logs/labip.log", encoding="utf-8")
        file_handler.setFormatter(fmt)
        file_handler.addFilter(mask_filter)
        handlers.append(file_handler)
        file_logging_ok = True
    except PermissionError:
        # 볼륨 마운트 시 호스트 디렉터리 권한이 컨테이너 사용자와 다를 때 발생.
        # 파일 로그 없이 콘솔만 사용한다.
        pass

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    for h in handlers:
        root_logger.addHandler(h)

    # discord.py 내부 로그 레벨 조정
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)

    if not file_logging_ok:
        logging.getLogger(__name__).warning(
            "logs/labip.log 에 쓸 수 없습니다 (권한 오류). "
            "콘솔 로그만 출력됩니다. "
            "해결: 호스트에서 'chmod 777 logs/' 실행 후 컨테이너 재시작"
        )


def get_seoul_time() -> datetime:
    """현재 시각을 Asia/Seoul 기준으로 반환한다."""
    return datetime.now(SEOUL_TZ)


def format_datetime(dt: datetime) -> str:
    """datetime을 'YYYY-MM-DD HH:MM:SS' 형식으로 포매팅한다."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_duration(seconds: float) -> str:
    """초 단위 소요 시간을 사람이 읽기 쉬운 형태로 반환한다."""
    total = int(seconds)
    if total < 60:
        return f"{total}초"
    minutes, secs = divmod(total, 60)
    return f"{minutes}분 {secs}초"
