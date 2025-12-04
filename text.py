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
            "Выберите цвет волос модели.\n\n"
            "Важно: позже можно будет добавить поддержку нескольких вариантов, "
            "сейчас выбирается один."
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
            "Выберите стиль фото на выходе.\n\n"
            "Стиль влияет на то, как нейросеть обработает одежду и модель."
        ),
        "btn_style_strict": "Строгий",
        "btn_style_luxury": "Люксовый",
        "btn_style_casual": "Кэжуал",
        "btn_style_sport": "Спортивный",

        # соотношение сторон
        "settings_aspect_title": (
            "Выберите соотношение сторон кадра.\n\n"
            "Все фото создаются в разрешении 4K."
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
            "Choose model hair color.\n\n"
            "Multiple options will be supported later, now only one can be selected."
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
            "Choose the output photo style.\n\n"
            "It affects how the model and clothing will look."
        ),
        "btn_style_strict": "Strict",
        "btn_style_luxury": "Luxury",
        "btn_style_casual": "Casual",
        "btn_style_sport": "Sport",

        "settings_aspect_title": (
            "Choose aspect ratio for the image.\n\n"
            "All images are generated in 4K resolution."
        ),
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
    },
}
