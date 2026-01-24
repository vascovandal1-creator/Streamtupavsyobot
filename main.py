"""Entry point for hosting.

Этот main.py сделан устойчивым: он пробует импортировать bot-модуль под разными именами.
Переименовал файл бота? Просто добавь имя модуля в список candidates ниже.

ОЖИДАНИЕ: в bot-модуле должна быть функция main().
"""

def _import_main():
    candidates = [
        "bot",                 # bot.py (по умолчанию)
        "bot_new",             # если файл назван bot_new.py
        "streamtupavsyobot",   # если файл назван streamtupavsyobot.py
        "app",                 # частое имя в хостингах
        "main_bot",            # запасной вариант
    ]
    last_err = None
    for mod in candidates:
        try:
            m = __import__(mod, fromlist=["main"])
            if hasattr(m, "main"):
                return m.main
        except Exception as e:
            last_err = e
    raise RuntimeError(
        "Не смог найти функцию main() в модулях: "
        + ", ".join(candidates)
        + (f" | Последняя ошибка: {last_err}" if last_err else "")
    )

main = _import_main()

if __name__ == "__main__":
    main()
