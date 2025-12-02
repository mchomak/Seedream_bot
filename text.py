# text.py
phrases = {
    "ru": {
        # --- старт и базовые вещи ---
        "start_title": "Привет! Это бот виртуальной примерочной Seedream.",
        "start_desc": (
            "Я помогу превратить фото вашей одежды в реалистичные кадры на моделях.\n\n"
            "Загрузите фото вещи, выберите фон, стиль, параметры модели — "
            "а я подготовлю промпт и отправлю запрос в нейросеть Seedream 4.0.\n\n"
            "Пока генерация в разработке, но вы уже можете настраивать профиль и пополнять баланс звёздами."
        ),
        "help_header": "Доступные команды",

        # --- описания команд в /help и меню бота ---
        "help_items": {
            "start": "Сбросить состояние и показать приветственное сообщение",
            "help": "Показать справку по командам",
            "profile": "Показать профиль и баланс",
            "generate": "Начать сценарий генерации (пока в режиме заглушки)",
            "examples": "Посмотреть примеры (заглушка)",
            "buy": "Пополнить баланс звёздами",
            "language": "Выбрать язык интерфейса",
            "cancel": "Отменить текущий сценарий",
        },

        # --- профиль ---
        "profile_not_found": "Профиль ещё не создан. Напишите /start, чтобы начать.",
        "profile_title": "Ваш профиль",
        "profile_line_id": "ID: {user_id}",
        "profile_line_user": "Username: @{username}",
        "profile_line_lang": "Текущий язык: {lang}",
        "profile_line_created": "Создан: {created}",
        "profile_line_last_seen": "Последняя активность: {last_seen}",
        "profile_line_txn": "Успешных пополнений: {count} шт. на сумму {sum} {cur}",
        "profile_line_balance_credits": "Кредиты (генерации): {balance}",
        "profile_line_balance_money": "Денежный баланс: {balance} ₽",

        # --- оплата звёздами ---
        "invoice_title": "Пополнение баланса (звёзды)",
        "invoice_desc": (
            "Оплатите удобное количество звёзд. В этом демо 1 звезда = 1 кредит генерации.\n"
            "После оплаты баланс будет автоматически пополнен."
        ),
        "payment_ok": (
            "Оплата звёздами прошла успешно.\n"
            "ID транзакции: {charge_id}\n"
            "Начислено звёзд: {amount}"
        ),

        # --- язык ---
        "choose_lang_title": "Выберите язык интерфейса:",
        "unknown_lang": "Неизвестный язык. Попробуйте ещё раз.",
        "lang_switched": "Язык интерфейса переключен на: {lang}",

        # --- доменные команды ---
        "examples_soon": (
            "Раздел с примерами пока в разработке.\n"
            "Позже здесь появятся реальные кейсы, собранные из ваших генераций."
        ),
        "cancel_done": "Текущий сценарий отменён. Вы в главном меню.",

        "generate_stub_registered": (
            "Запрос на генерацию зарегистрирован (ID: {gen_id}).\n"
            "Логика конструктора и вызова Seedream 4.0 будет подключена на следующем этапе разработки."
        ),
    },

    "en": {
        # --- start & basics ---
        "start_title": "Hi! This is the Seedream virtual try-on bot.",
        "start_desc": (
            "I help you turn photos of your clothing items into realistic model shots.\n\n"
            "Upload a photo of an item, choose background, style and model parameters — "
            "I will build a prompt and send it to the Seedream 4.0 model.\n\n"
            "Generation flow is still under development, but you can already manage your profile "
            "and top up balance with Telegram Stars."
        ),
        "help_header": "Available commands",

        # --- command descriptions ---
        "help_items": {
            "start": "Reset state and show the welcome message",
            "help": "Show this help",
            "profile": "Show profile and balance",
            "generate": "Start generation flow (currently stub only)",
            "examples": "See examples (stub)",
            "buy": "Top up balance with Stars",
            "language": "Change interface language",
            "cancel": "Cancel current scenario",
        },

        # --- profile ---
        "profile_not_found": "Profile is not created yet. Send /start to begin.",
        "profile_title": "Your profile",
        "profile_line_id": "ID: {user_id}",
        "profile_line_user": "Username: @{username}",
        "profile_line_lang": "Current language: {lang}",
        "profile_line_created": "Created at: {created}",
        "profile_line_last_seen": "Last activity: {last_seen}",
        "profile_line_txn": "Successful top-ups: {count} for total {sum} {cur}",
        "profile_line_balance_credits": "Credits (generations): {balance}",
        "profile_line_balance_money": "Money balance: {balance} ₽",

        # --- stars payment ---
        "invoice_title": "Balance top-up (Stars)",
        "invoice_desc": (
            "Pay any amount of Stars. In this demo 1 Star = 1 generation credit.\n"
            "After payment your balance will be updated automatically."
        ),
        "payment_ok": (
            "Stars payment succeeded.\n"
            "Transaction ID: {charge_id}\n"
            "Stars credited: {amount}"
        ),

        # --- language ---
        "choose_lang_title": "Choose interface language:",
        "unknown_lang": "Unknown language. Please try again.",
        "lang_switched": "Interface language switched to: {lang}",

        # --- domain commands ---
        "examples_soon": (
            "Examples section is under development.\n"
            "Later you will see real-world samples collected from your generations."
        ),
        "cancel_done": "Current scenario has been cancelled. You are back to the main menu.",

        "generate_stub_registered": (
            "Generation request registered (ID: {gen_id}).\n"
            "Prompt builder and Seedream 4.0 invocation will be wired in the next development step."
        ),
    },
}
