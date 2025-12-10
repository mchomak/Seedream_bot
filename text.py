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

        # Persistent keyboard buttons
        "kb_generation": "🎨 Генерация",
        "kb_my_account": "👤 Мой аккаунт",
        "kb_examples": "📸 Примеры",

        # Account menu
        "account_menu": "👤 <b>Мой аккаунт</b>\n\nВыберите раздел:",
        "btn_balance": "💰 Баланс",
        "btn_history": "📜 История",
        "btn_back": "◀️ Назад",

        # Balance view
        "balance_title": "💰 <b>Ваш баланс</b>",
        "balance_generations": "Генераций: <b>{count}</b>",
        "balance_rubles": "Рублей: <b>{amount} ₽</b>",
        "balance_price_per_gen": "Стоимость 1 генерации: <b>{price} ₽</b>",
        "btn_topup": "💳 Пополнить баланс",

        # Payment method selection
        "payment_method_title": "💳 <b>Выберите способ оплаты</b>",
        "payment_method_desc": "Выберите удобный для вас способ пополнения баланса:",
        "btn_pay_stars": "⭐️ Telegram Stars",
        "btn_pay_yookassa": "💳 Банковская карта (YooKassa)",
        "payment_stars_desc": "Оплата через Telegram Stars",
        "payment_yookassa_desc": "Оплата банковской картой через YooKassa",
        "yookassa_not_configured": "❌ Оплата через YooKassa временно недоступна",

        # YooKassa payment flow
        "yookassa_payment_created": (
            "🧾 <b>Платеж создан!</b>\n\n"
            "💰 Сумма: {amount} {currency}\n"
            "📝 Описание: {description}\n"
            "🆔 ID платежа: <code>{payment_id}</code>\n\n"
            "Нажмите кнопку ниже для перехода к оплате."
        ),
        "btn_pay_now": "💳 Перейти к оплате",
        "btn_check_payment": "✅ Проверить оплату",
        "yookassa_payment_error": "❌ Ошибка при создании платежа.\nПопробуйте позже.",
        "yookassa_checking": "Проверяем статус платежа...",
        "yookassa_status_pending": "⏳ Платеж ожидает оплаты",
        "yookassa_status_waiting": "⏳ Платеж ожидает подтверждения",
        "yookassa_status_succeeded": (
            "✅ <b>Платеж успешно завершен!</b>\n\n"
            "💰 Сумма: {amount} {currency}\n"
            "🆔 ID платежа: <code>{payment_id}</code>\n\n"
            "Спасибо за оплату! Баланс обновлен."
        ),
        "yookassa_status_canceled": "❌ Платеж отменен",
        "yookassa_check_error": "❌ Ошибка при проверке платежа.\nПопробуйте позже.",
        "btn_create_new_payment": "🔄 Создать новый платеж",

        # History view
        "history_title": "📜 <b>История генераций</b>",
        "history_empty": "У вас пока нет завершённых генераций.",
        "history_item": (
            "📅 {datetime}\n"
            "💰 Стоимость: {cost} кредитов\n"
            "📝 Параметры: {params}"
        ),
        "btn_download": "⬇️ Скачать",
        "btn_use_as_base": "🎨 Использовать как базу",
        "btn_prev_page": "◀️ Назад",
        "btn_next_page": "Вперёд ▶️",
        "history_page": "Страница {page} из {total}",
        "history_month_limit": "Показаны генерации за последний месяц",

        # --- описания команд в /help и меню бота ---
        "help_items": {
            "start": "Сбросить состояние и показать приветственное сообщение",
            "help": "Показать справку по командам",
            "profile": "Показать профиль и баланс",
            "generate": "Сгенерировать примерочный кадр по фото вещи",
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
        # --- генерация / сценарии Seedream ---
        "no_credits": "Недостаточно кредитов для генерации. Пополните баланс через /buy.",
        "send_photo_prompt": (
            "Отправьте, пожалуйста, фото вещи.\n\n"
            "Подходит: одежда на человеке, манекене или вешалке, главное — чтобы сама вещь "
            "была хорошо видна."
        ),
        "processing_generation": "Обрабатываю изображение и запускаю генерацию…",
        "generation_failed": "Не удалось выполнить генерацию. Попробуйте ещё раз или обратитесь в поддержку.",
        "generation_done": "Готово! Вот сгенерированный кадр.",

        # подписи для разных сценариев (если будешь показывать юзеру)
        "scenario_initial_generation": "Базовая генерация примерочного кадра",
        "scenario_regenerate_same": "Повторная генерация с теми же настройками",
        "scenario_regenerate_new": "Повторная генерация с новыми настройками",
        "scenario_change_pose": "Смена позы",
        "scenario_change_angle": "Смена ракурса",
        "scenario_back_view": "Ракурс сзади",
        "scenario_full_body": "Кадр в полный рост",
        "scenario_upper_body": "Кадр по верхнюю часть тела",
        "scenario_lower_body": "Кадр по нижнюю часть тела",
        # --- generate flow: первый шаг и загрузка фото ---
        "generate_intro_short": (
            "Чтобы создать примерочный кадр, нужно загрузить фото вещи и задать параметры.\n\n"
            "Нажмите «Начать», чтобы изучить рекомендации к фото и выбрать тип снимка."
        ),
        "upload_intro_full": (
            "<b>Загрузите фотографии вещей, которые хотите надеть на модель.</b>\n\n"
            "Шаг 1. Изучите рекомендации:\n"
            "- Обрежьте фото: оставьте минимум лишнего помимо нужной одежды.\n"
            "- На фото не должно быть лиц и голов людей или манекенов.\n"
            "- Чем выше разрешение фото, тем лучше результат.\n"
            "- Сложная металлическая фурнитура может отображаться некорректно.\n"
            "- Отображение одежды на молниях может потребовать больше попыток.\n\n"
            "Шаг 2. Выберите тип загружаемой фотографии:\n"
            "- Фото одежды (лежит или висит на вешалке)\n"
            "- Фото на человеке (без лица и лишних элементов)\n"
            "- Фото на манекене (без головы манекена)\n\n"
            "Шаг 3. Загрузите фотографию одной или нескольких вещей.\n"
            "Важно: каждое загруженное фото считается отдельной вещью."
        ),

        # кнопки
        "btn_start": "Начать",
        "btn_back": "Назад",
        "btn_upload_flat": "Фото одежды",
        "btn_upload_on_person": "Фото на человеке",
        "btn_upload_on_mannequin": "Фото на манекене",

        # уточняющие тексты под конкретный тип
        "prompt_upload_flat": (
            "Загрузите фотографию одежды на нейтральном фоне.\n"
            "Одежда может лежать или висеть на вешалке.\n"
            "Рекомендуем обрезать фото так, чтобы на нём оставалась только одежда, "
            "которую вы хотите надеть на модель.\n\n"
            "Отправьте изображение <b>как документ</b>, чтобы сохранить качество."
        ),
        "prompt_upload_on_person": (
            "ВАЖНО: на фото не должно быть лиц и голов людей.\n"
            "Рекомендуем обрезать фотографию так, чтобы на нём оставалась только одежда, "
            "которую вы хотите надеть на модель.\n\n"
            "Отправьте изображение <b>как документ</b>, чтобы сохранить качество."
        ),
        "prompt_upload_on_mannequin": (
            "ВАЖНО: на фото не должно быть головы манекена.\n"
            "Рекомендуем обрезать фотографию так, чтобы на нём оставалась только одежда, "
            "которую вы хотите надеть на модель.\n\n"
            "Отправьте изображение <b>как документ</b>, чтобы сохранить качество."
        ),

        "upload_doc_wrong_type": (
            "Пожалуйста, отправьте фото как <b>документ</b> (оригинальное качество), "
            "а не как сжатое изображение."
        ),

        "task_queued": (
            "Задача поставлена в очередь (ID: {task_id}).\n"
            "Идёт обработка на сервере нейросети."
        ),
            # --- конструктор промпта (шаги) ---
        "settings_intro_single": (
            "Вы загрузили {count} вещь.\n\n"
            "Далее вы сможете выбрать фон, пол, возраст и цвет волос модели, "
            "стиль фото и соотношение сторон."
        ),

        # фон
        "settings_background_title": (
            "Выберите цвет фона для создания фото вашей вещи на модели.\n\n"
            "Важно: выбор фона влияет на итоговый вид фото."
        ),
        "btn_bg_white": "Белый фон",
        "btn_bg_beige": "Бежевый фон",
        "btn_bg_pink": "Розовый фон",
        "btn_bg_black": "Чёрный фон",

        # пол
        "settings_gender_title": "Выберите пол модели:",
        "btn_gender_female": "Женщина",
        "btn_gender_male": "Мужчина",

        # цвет волос
        "settings_hair_title": (
            "Выберите один или несколько цветов волос модели.\n\n"
            "ВАЖНО: выбор нескольких вариантов в этом и других пунктах (фон, стиль, соотношение сторон) "
            "перемножает количество создаваемых фото.\n"
            "Вариант «Любой» не увеличивает количество фото и не добавляет уточнение по цвету волос в промпт."
        ),
        "btn_hair_any": "Любой",
        "btn_hair_dark": "Тёмные",
        "btn_hair_light": "Светлые",

        # возраст
        "settings_age_title": "Выберите возраст модели:",
        "btn_age_young": "Молодой взрослый (по умолчанию)",
        "btn_age_senior": "Пожилой",
        "btn_age_child": "Ребёнок",
        "btn_age_teen": "Подросток",

        # стиль
        "settings_style_title": (
            "Выберите один или несколько стилей фото на выходе.\n\n"
            "Стиль влияет на то, как нейросеть обработает одежду и модель. "
            "Несколько стилей увеличивают количество создаваемых фото."
        ),
        "btn_style_strict": "Строгий",
        "btn_style_luxury": "Люксовый",
        "btn_style_casual": "Кэжуал",
        "btn_style_sport": "Спортивный",

        "hair_selected_header": "Выбранные цвета волос:",
        "hair_need_one": "Выберите хотя бы один вариант цвета волос, чтобы продолжить.",

        "style_selected_header": "Выбранные стили:",
        "style_need_one": "Выберите хотя бы один стиль, чтобы продолжить.",

        "aspect_selected_header": "Выбранные соотношения сторон:",
        "aspect_need_one": "Выберите хотя бы одно соотношение сторон, чтобы продолжить.",

        # соотношение сторон
        "settings_aspect_title": (
            "Выберите одно или несколько соотношений сторон кадра.\n\n"
            "Все фото создаются в разрешении 4K. "
            "Несколько соотношений сторон увеличивают количество фото."
        ),
        "btn_aspect_3_4": "3:4 (3072x4096) — маркетплейсы",
        "btn_aspect_9_16": "9:16 (2304x4096) — сторис",
        "btn_aspect_1_1": "1:1 (4096x4096) — квадрат",
        "btn_aspect_16_9": "16:9 (4096x2304) — широкий",

        # подтверждение
        "confirm_generation_title": (
            "<b>Проверка перед генерацией</b>\n\n"
            "Количество вещей: {items}\n"
            "Фон: {background}\n"
            "Пол: {gender}\n"
            "Волосы: {hair}\n"
            "Возраст: {age}\n"
            "Стиль: {style}\n"
            "Соотношение сторон: {aspect}\n\n"
            "Ваш баланс: {balance} генераций.\n"
            "Вы создаёте {photos} фото."
        ),
        "confirm_generation_ok": "Нажмите «Далее», чтобы создать фотографии.",
        "confirm_generation_not_enough": (
            "Недостаточно генераций на балансе. "
            "Пополните баланс через /buy или уменьшите количество запрашиваемых фото."
        ),

        # кнопки на шагах
        "btn_next": "Далее",
        "btn_confirm_next": "Далее",
        "btn_confirm_topup": "Пополнить баланс",

        # Photo review buttons
        "btn_approve": "✅ Утвердить",
        "btn_redo": "🔄 Переделать",
        "btn_reject": "❌ Отклонить",
        "btn_redo_same": "🔄 Переделать с теми же настройками",
        "btn_redo_new": "⚙️ Переделать с новыми настройками",
        "btn_return_menu": "🏠 Вернуться в главное меню",
        "btn_topup_balance": "💳 Пополнить баланс",

        # Photo review messages
        "photo_review_title": "Фото {current} из {total}",
        "photo_review_question": "Что сделать с этим фото?",
        "photo_approved": "Фото утверждено!",
        "photo_rejected": "Фото отклонено.",
        "redo_question": "Хотите переделать фото?",
        "insufficient_balance": "Недостаточно средств для повторной генерации. Пожалуйста, пополните баланс.",
        "no_more_photos": "Больше нет фотографий в очереди.",
        "all_photos_reviewed": "Все фотографии просмотрены. У вас есть {approved} утверждённых фото.",
        "moving_to_angles": "Переход к выбору новых ракурсов и поз...",

        # Angles and poses stage
        "angles_intro": "Добавьте новые позы и ракурсы для создания профиля товара на основе этого фото.",
        "angles_base_photo": "Базовое фото:",
        "btn_change_pose": "🧍 Сменить позу",
        "btn_change_pose_5x": "🧍🧍🧍 Сменить позу 5 раз",
        "btn_change_angle": "📐 Сменить ракурс",
        "btn_change_angle_5x": "📐📐📐 Сменить ракурс 5 раз",
        "btn_add_rear_view": "🔄 Добавить вид сзади",
        "btn_full_body": "👤 В полный рост (бета)",
        "btn_upper_body": "👔 Верх тела (бета)",
        "btn_lower_body": "👖 Низ тела (бета)",
        "btn_finish_photo": "✅ Завершить",

        "rear_view_prompt": "Загрузите фото этой вещи сзади",
        "btn_no_rear_photo": "❌ У меня нет фото сзади (менее эффективно)",

        "variant_result": "Результат генерации:",
        "btn_redo_variant": "🔄 Переделать",
        "btn_continue_variants": "➡️ Продолжить",

        "confirm_finish_photo": "Вы уверены, что хотите завершить работу с этим фото?",
        "btn_yes_finish": "✅ Да, завершить",
        "btn_no_continue": "❌ Нет, продолжить",

        "moving_to_next_base": "Переход к следующему базовому фото...",
        "all_base_photos_complete": "Все базовые фотографии обработаны!",

        "upload_doc_only": "Пожалуйста, отправьте фото как документ в оригинальном качестве (без сжатия).",
        "upload_doc_wrong_type": "Это не похоже на изображение. Пожалуйста, отправьте фотографию одежды как документ (файл).",

        "multi_items_not_supported": "Сейчас бот поддерживает генерацию только по одной вещи за раз. Сценарий для нескольких вещей скоро появится.",

        "settings_intro_single": (
            "Вы загрузили {count} вещь. Далее вы сможете выбрать фон, пол, возраст и цвет волос модели, "
            "соотношение сторон и стиль фото на выходе."
        ),

        "background_select_single": (
            "Выберите один или несколько цветов фона для создания фото ваших вещей на модели.\n"
            "ВАЖНО: При выборе нескольких фонов генерируется соответствующее количество фотографий, "
            "перемноженное на количество загруженных вещей."
        ),
        "background_selected_header": "Выбранные цвета фона:",
        "background_need_one": "Выберите хотя бы один цвет фона, чтобы продолжить.",

        "btn_bg_white": "Белый фон",
        "btn_bg_beige": "Бежевый фон",
        "btn_bg_pink": "Розовый фон",
        "btn_bg_black": "Чёрный фон",

        # короткие подписи для списка выбранных фонов
        "bg_label_white": "белый",
        "bg_label_beige": "бежевый",
        "bg_label_pink": "розовый",
        "bg_label_black": "чёрный",

        "btn_next": "Далее",
        "btn_back": "Назад",

        "gender_choose_title": "Выберите пол модели:",
        "btn_gender_female": "Женщина",
        "btn_gender_male": "Мужчина",
        "gender_selected_stub": (
            "Пол модели сохранён. На следующем шаге будет выбор цвета волос, возраста, стиля и соотношения сторон."
        ),
        "multi_items_intro": (
            "Вы загрузили {count} вещей.\n\n"
            "Далее вы сможете выбрать фон, пол, возраст и цвет волос модели, "
            "соотношение сторон и стиль фото на выходе.\n\n"
            "Что вам удобнее?"
            ),

        "btn_mode_all_items": "Задать единые настройки для всех вещей (быстрее)",
        "btn_mode_per_item": "Задать настройки для каждой вещи отдельно",

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

        # Persistent keyboard buttons
        "kb_generation": "🎨 Generation",
        "kb_my_account": "👤 My Account",
        "kb_examples": "📸 Examples",

        # Account menu
        "account_menu": "👤 <b>My Account</b>\n\nChoose a section:",
        "btn_balance": "💰 Balance",
        "btn_history": "📜 History",
        "btn_back": "◀️ Back",

        # Balance view
        "balance_title": "💰 <b>Your Balance</b>",
        "balance_generations": "Generations: <b>{count}</b>",
        "balance_rubles": "Rubles: <b>{amount} ₽</b>",
        "balance_price_per_gen": "Price per generation: <b>{price} ₽</b>",
        "btn_topup": "💳 Top Up Balance",

        # Payment method selection
        "payment_method_title": "💳 <b>Choose Payment Method</b>",
        "payment_method_desc": "Select your preferred payment method to top up balance:",
        "btn_pay_stars": "⭐️ Telegram Stars",
        "btn_pay_yookassa": "💳 Bank Card (YooKassa)",
        "payment_stars_desc": "Payment via Telegram Stars",
        "payment_yookassa_desc": "Bank card payment via YooKassa",
        "yookassa_not_configured": "❌ YooKassa payment is temporarily unavailable",

        # YooKassa payment flow
        "yookassa_payment_created": (
            "🧾 <b>Payment Created!</b>\n\n"
            "💰 Amount: {amount} {currency}\n"
            "📝 Description: {description}\n"
            "🆔 Payment ID: <code>{payment_id}</code>\n\n"
            "Click the button below to proceed with payment."
        ),
        "btn_pay_now": "💳 Proceed to Payment",
        "btn_check_payment": "✅ Check Payment Status",
        "yookassa_payment_error": "❌ Error creating payment.\nPlease try again later.",
        "yookassa_checking": "Checking payment status...",
        "yookassa_status_pending": "⏳ Payment pending",
        "yookassa_status_waiting": "⏳ Payment awaiting confirmation",
        "yookassa_status_succeeded": (
            "✅ <b>Payment Successful!</b>\n\n"
            "💰 Amount: {amount} {currency}\n"
            "🆔 Payment ID: <code>{payment_id}</code>\n\n"
            "Thank you! Your balance has been updated."
        ),
        "yookassa_status_canceled": "❌ Payment canceled",
        "yookassa_check_error": "❌ Error checking payment status.\nPlease try again later.",
        "btn_create_new_payment": "🔄 Create New Payment",

        # History view
        "history_title": "📜 <b>Generation History</b>",
        "history_empty": "You don't have any completed generations yet.",
        "history_item": (
            "📅 {datetime}\n"
            "💰 Cost: {cost} credits\n"
            "📝 Parameters: {params}"
        ),
        "btn_download": "⬇️ Download",
        "btn_use_as_base": "🎨 Use as Base",
        "btn_prev_page": "◀️ Previous",
        "btn_next_page": "Next ▶️",
        "history_page": "Page {page} of {total}",
        "history_month_limit": "Showing generations from the last month",

        "multi_items_intro": (
            "You have uploaded {count} items.\n\n"
            "Next you will choose background, model gender, age, hair color, "
            "photo style and aspect ratio for the images.\n\n"
            "How would you like to proceed?"
        ),

        "btn_mode_all_items": "Use the same settings for all items (faster)",
        "btn_mode_per_item": "Set settings for each item separately",


        # --- command descriptions ---
        "help_items": {
            "start": "Reset state and show the welcome message",
            "help": "Show this help",
            "profile": "Show profile and balance",
            "generate": "Generate virtual try-on shot from clothing photo",
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
        # --- generation / Seedream scenarios ---
        "no_credits": "You don't have enough credits for generation. Please top up via /buy.",
        "send_photo_prompt": (
            "Please send a photo of the clothing item.\n\n"
            "It can be worn on a person, on a mannequin, or on a hanger, "
            "as long as the item is clearly visible."
        ),
        "processing_generation": "Processing your image and starting generation…",
        "generation_failed": "Failed to generate an image. Please try again or contact support.",
        "generation_done": "Done! Here is your generated shot.",

        "scenario_initial_generation": "Initial try-on generation",
        "scenario_regenerate_same": "Regenerate with the same settings",
        "scenario_regenerate_new": "Regenerate with new settings",
        "scenario_change_pose": "Change pose",
        "scenario_change_angle": "Change angle",
        "scenario_back_view": "Back view",
        "scenario_full_body": "Full body shot",
        "scenario_upper_body": "Upper body shot",
        "scenario_lower_body": "Lower body shot",
        # --- generate flow: first step & upload photo ---
        "generate_intro_short": (
            "To create a try-on shot, you need to upload a clothing photo and set parameters.\n\n"
            "Tap “Start” to see photo guidelines and choose the photo type."
        ),
        "upload_intro_full": (
            "<b>Upload photos of the items you want to put on the model.</b>\n\n"
            "Step 1. Read the guidelines:\n"
            "- Crop the photo to remove anything that is not the clothing item.\n"
            "- There must be no human or mannequin heads in the image.\n"
            "- Higher resolution gives better results.\n"
            "- Complex metallic hardware may not be rendered perfectly.\n"
            "- Zippers may require more attempts to look correct.\n\n"
            "Step 2. Choose the type of your photo:\n"
            "- Clothing only (lying or hanging)\n"
            "- On a person (no face, minimum distractions)\n"
            "- On a mannequin (no mannequin head)\n\n"
            "Step 3. Upload a photo of one or several items.\n"
            "Important: each uploaded photo counts as a separate item."
        ),

        "btn_start": "Start",
        "btn_back": "Back",
        "btn_upload_flat": "Clothing only",
        "btn_upload_on_person": "On a person",
        "btn_upload_on_mannequin": "On a mannequin",

        "prompt_upload_flat": (
            "Please upload a photo of the clothing item on a neutral background.\n"
            "It can lie flat or hang on a hanger.\n"
            "We recommend cropping the image so that only the clothing you want to put "
            "on the model remains.\n\n"
            "Send the image <b>as a document</b> to keep full quality."
        ),
        "prompt_upload_on_person": (
            "IMPORTANT: there must be no faces or heads in the image.\n"
            "We recommend cropping the photo so that only the clothing you want to put "
            "on the model remains.\n\n"
            "Send the image <b>as a document</b> to keep full quality."
        ),
        "prompt_upload_on_mannequin": (
            "IMPORTANT: the mannequin head must not be visible.\n"
            "We recommend cropping the photo so that only the clothing you want to put "
            "on the model remains.\n\n"
            "Send the image <b>as a document</b> to keep full quality."
        ),

        "upload_doc_wrong_type": (
            "Please send the photo <b>as a document</b> (original quality), "
            "not as a compressed image."
        ),

        "task_queued": (
            "Your request has been queued (ID: {task_id}).\n"
            "The model is processing it now."
        ),
                # --- prompt builder (steps) ---
        "settings_intro_single": (
            "You have uploaded {count} item.\n\n"
            "Next you will choose background, model gender, age, hair color, "
            "photo style and aspect ratio."
        ),

        "settings_background_title": (
            "Choose background color for your try-on photo.\n\n"
            "Background affects the final look of the image."
        ),
        "btn_bg_white": "White background",
        "btn_bg_beige": "Beige background",
        "btn_bg_pink": "Pink background",
        "btn_bg_black": "Black background",

        "settings_gender_title": "Choose model gender:",
        "btn_gender_female": "Female",
        "btn_gender_male": "Male",

        "settings_hair_title": (
            "Select one or more hair colors for the model.\n\n"
            "IMPORTANT: choosing multiple options here and in other steps "
            "(background, style, aspect ratio) multiplies the number of images.\n"
            "Option “Any” does not increase the image count and does not add a hair-color constraint to the prompt."
        ),
        "btn_hair_any": "Any",
        "btn_hair_dark": "Dark",
        "btn_hair_light": "Light",

        "settings_age_title": "Choose model age:",
        "btn_age_young": "Young adult (default)",
        "btn_age_senior": "Senior",
        "btn_age_child": "Child",
        "btn_age_teen": "Teenager",

        "settings_style_title": (
            "Select one or more output photo styles.\n\n"
            "The style affects how the model and clothing will look. "
            "Multiple styles increase the number of generated images."
        ),
        "btn_style_strict": "Strict",
        "btn_style_luxury": "Luxury",
        "btn_style_casual": "Casual",
        "btn_style_sport": "Sport",

        "settings_aspect_title": (
            "Select one or more aspect ratios.\n\n"
            "All images are generated in 4K resolution. "
            "Multiple aspect ratios increase the number of images."
        ),
        "hair_selected_header": "Selected hair colors:",
        "hair_need_one": "Please select at least one hair color to continue.",

        "style_selected_header": "Selected styles:",
        "style_need_one": "Please select at least one style to continue.",

        "aspect_selected_header": "Selected aspect ratios:",
        "aspect_need_one": "Please select at least one aspect ratio to continue.",

        "btn_aspect_3_4": "3:4 (3072x4096) — marketplaces",
        "btn_aspect_9_16": "9:16 (2304x4096) — stories",
        "btn_aspect_1_1": "1:1 (4096x4096) — square",
        "btn_aspect_16_9": "16:9 (4096x2304) — wide",

        "confirm_generation_title": (
            "<b>Pre-generation check</b>\n\n"
            "Items: {items}\n"
            "Background: {background}\n"
            "Gender: {gender}\n"
            "Hair: {hair}\n"
            "Age: {age}\n"
            "Style: {style}\n"
            "Aspect ratio: {aspect}\n\n"
            "Your balance: {balance} generations.\n"
            "You are about to create {photos} image(s)."
        ),
        "confirm_generation_ok": "Tap “Next” to start generation.",
        "confirm_generation_not_enough": (
            "You don't have enough generations. "
            "Top up via /buy or reduce the number of requested images."
        ),

        "btn_next": "Next",
        "btn_confirm_next": "Next",
        "btn_confirm_topup": "Top up balance",

        # Photo review buttons
        "btn_approve": "✅ Approve",
        "btn_redo": "🔄 Redo",
        "btn_reject": "❌ Reject",
        "btn_redo_same": "🔄 Redo with same settings",
        "btn_redo_new": "⚙️ Redo with new settings",
        "btn_return_menu": "🏠 Return to main menu",
        "btn_topup_balance": "💳 Top up balance",

        # Photo review messages
        "photo_review_title": "Photo {current} of {total}",
        "photo_review_question": "What would you like to do with this photo?",
        "photo_approved": "Photo approved!",
        "photo_rejected": "Photo rejected.",
        "redo_question": "Would you like to redo the photo?",
        "insufficient_balance": "Insufficient balance for regeneration. Please top up your balance.",
        "no_more_photos": "No more photos in queue.",
        "all_photos_reviewed": "All photos reviewed. You have {approved} approved photo(s).",
        "moving_to_angles": "Moving to new angles and poses selection...",

        # Angles and poses stage
        "angles_intro": "Add new poses and camera angles to create a product profile based on this photo.",
        "angles_base_photo": "Base photo:",
        "btn_change_pose": "🧍 Change pose",
        "btn_change_pose_5x": "🧍🧍🧍 Change pose 5 times",
        "btn_change_angle": "📐 Change angle",
        "btn_change_angle_5x": "📐📐📐 Change angle 5 times",
        "btn_add_rear_view": "🔄 Add rear view",
        "btn_full_body": "👤 Full body (beta)",
        "btn_upper_body": "👔 Upper body (beta)",
        "btn_lower_body": "👖 Lower body (beta)",
        "btn_finish_photo": "✅ Finish",

        "rear_view_prompt": "Upload a photo of this item from behind",
        "btn_no_rear_photo": "❌ I don't have a photo from behind (less effective)",

        "variant_result": "Generation result:",
        "btn_redo_variant": "🔄 Redo",
        "btn_continue_variants": "➡️ Continue",

        "confirm_finish_photo": "Are you sure you want to finish with this photo?",
        "btn_yes_finish": "✅ Yes, finish",
        "btn_no_continue": "❌ No, continue",

        "moving_to_next_base": "Moving to next base photo...",
        "all_base_photos_complete": "All base photos processed!",

        "upload_doc_only": "Please send the photo as a document in original quality (without compression).",
        "upload_doc_wrong_type": "This does not look like an image. Please send the clothing photo as a document (file).",

        "multi_items_not_supported": "Currently the bot supports generation for a single item only. Multi-item flow is coming soon.",

        "settings_intro_single": (
            "You have uploaded {count} item. Next you will select background, model gender, age and hair color, "
            "aspect ratio and photo style."
        ),

        "background_select_single": (
            "Select one or more background colors to generate photos of your items on a model.\n"
            "IMPORTANT: If you select multiple backgrounds, the number of generated photos "
            "will be multiplied by the number of uploaded items."
        ),
        "background_selected_header": "Selected background colors:",
        "background_need_one": "Please select at least one background color to continue.",

        "btn_bg_white": "White background",
        "btn_bg_beige": "Beige background",
        "btn_bg_pink": "Pink background",
        "btn_bg_black": "Black background",

        "bg_label_white": "white",
        "bg_label_beige": "beige",
        "bg_label_pink": "pink",
        "bg_label_black": "black",

        "btn_next": "Next",
        "btn_back": "Back",

        "gender_choose_title": "Choose the model gender:",
        "btn_gender_female": "Female",
        "btn_gender_male": "Male",
        "gender_selected_stub": (
            "Model gender has been saved. The next steps will be hair color, age, style and aspect ratio."
        ),

    },
}