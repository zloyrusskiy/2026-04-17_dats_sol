import time
from loguru import logger
from cherviak.brain import decide_turn
from cherviak.client import GameClient
from cherviak.config import load_config


def run() -> None:
    config = load_config()
    logger.info(f"Бот стартовал, base_url={config.base_url}")

    last_processed_turn = -1

    with GameClient(config) as client:
        while True:
            try:
                arena = client.get_arena()
            except Exception as e:
                logger.warning(f"Не удалось получить арену: {e}")
                time.sleep(1.0)
                continue

            if arena.turn_no == last_processed_turn:
                # Уже отправили команду в этом ходу — ждём следующий
                time.sleep(min(max(arena.next_turn_in, 0.05), 0.2))
                continue

            last_processed_turn = arena.turn_no
            hq_pos = next((p.position for p in arena.plantations if p.is_main), None)
            logger.info(
                f"Ход {arena.turn_no}: plantations={len(arena.plantations)}, "
                f"hq={hq_pos}, upgrade_points={arena.plantation_upgrades.points}"
            )

            try:
                body = decide_turn(arena)
            except Exception:
                logger.exception(f"Ошибка принятия решения в ходу {arena.turn_no}")
                body = None

            if body is None:
                logger.info(f"Ход {arena.turn_no}: нет действий — пропускаем")
            else:
                try:
                    response = client.post_command(body)
                    errors = response.get("errors") or []
                    if errors:
                        logger.warning(f"Ход {arena.turn_no}: ошибки сервера: {errors}")
                    else:
                        logger.info(f"Ход {arena.turn_no}: команда принята")
                except Exception:
                    logger.exception(f"Ошибка отправки команды в ходу {arena.turn_no}")

            time.sleep(max(arena.next_turn_in, 0.05))


if __name__ == "__main__":
    run()
