"""
진입점 모듈.
실행: python -m app.main
"""

import asyncio
import logging
import sys

from dotenv import load_dotenv

from app.config import load_config
from app.utils import setup_logging

# .env 파일이 있으면 환경변수로 로드 (Docker 환경에선 env_file로 주입되므로 무시됨)
load_dotenv()


async def _run() -> None:
    from aiohttp import web

    from app.bot import LabIPBot
    from app.data import IPRegistry
    from app.tokens import TokenStore
    from app.webserver import create_web_app

    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("=== 연구실 IP 등록 봇 시작 ===")

    try:
        config = load_config()
    except (KeyError, ValueError) as e:
        logger.critical(f"설정 로드 실패: {e}")
        sys.exit(1)

    guild_list = ", ".join(str(g.guild_id) for g in config.guilds)
    logger.info(
        f"설정 로드 성공 — 허용 대역: {config.ip_prefix}.x, "
        f"길드 {len(config.guilds)}개: [{guild_list}]"
    )

    # 공유 저장소 초기화
    registry = IPRegistry(config.ip_state_file)
    token_store = TokenStore(config.token_file)
    logger.info(f"현재 등록 IP 수: {registry.count()}개")

    # 웹서버 시작
    web_app = create_web_app(
        registry, token_store, config.ip_prefix,
        rate_limit_window=config.rate_limit_window,
        rate_limit_max=config.rate_limit_max,
    )
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, config.web_host, config.web_port)
    await site.start()
    logger.info(f"웹서버 시작: {config.web_host}:{config.web_port}  (공개 URL: {config.web_base_url})")

    # 봇 실행
    bot = LabIPBot(config, registry, token_store)
    try:
        # log_handler=None: 로깅은 setup_logging()에서 이미 설정
        await bot.start(config.discord_token, reconnect=True)
    except KeyboardInterrupt:
        logger.info("사용자에 의해 봇이 중지되었습니다.")
    except Exception as e:
        logger.critical(f"봇 실행 중 치명적 오류: {e}", exc_info=True)
    finally:
        if not bot.is_closed():
            await bot.close()
        await runner.cleanup()
        logger.info("봇 종료.")


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
