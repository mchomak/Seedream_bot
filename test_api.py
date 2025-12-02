import os
import time
import typing as t

import requests


# === Настройки API ===

API_BASE_URL = "c2d5c6a1e2082539c22f5dfdedc98005"

# ВАЖНО:
# Проверь в своей документации Seedream 4.0 на Kie.ai точные пути.
# Часто формат такой: /api/v1/<model>/generate и /api/v1/<model>/record-info
# Здесь оставлен примерный вариант, который нужно при необходимости поправить.
SEEDREAM_MODEL_SLUG = "seedream"  # TODO: уточнить: 'seedream', 'seedream4', 'seedream-v4' и т.п.

SEEDREAM_GENERATE_ENDPOINT = f"{API_BASE_URL}/{SEEDREAM_MODEL_SLUG}/generate"
SEEDREAM_RECORD_INFO_ENDPOINT = f"{API_BASE_URL}/{SEEDREAM_MODEL_SLUG}/record-info"

API_KEY = os.getenv("KIE_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "Переменная окружения KIE_API_KEY не задана. "
        "Создай API-ключ в Kie.ai и экспортируй его, например:\n"
        "export KIE_API_KEY='your_api_key_here'"
    )


class SeedreamClient:
    """
    Простой клиент для Seedream 4.0 на Kie.ai:
    - создание задач (text-to-image, edit)
    - опрос статуса задачи
    """

    def __init__(self, api_key: str, timeout: int = 60):
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def _post(self, url: str, payload: dict) -> dict:
        resp = self.session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        print(f"[POST] {url} -> {data}")
        return data

    def _get(self, url: str, params: dict) -> dict:
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        print(f"[GET] {url} -> {data}")
        return data

    # --- Базовые операции ---

    def create_task_edit(
        self,
        prompt: str,
        image_urls: list[str],
        image_size: str = "Portrait 3:4",
        image_resolution: str = "4K",
        max_images: int = 1,
        seed: t.Optional[int] = None,
    ) -> dict:
        """
        Создаёт задачу редактирования (Seedream V4 Edit).
        Формат полей основан на форме Seedream 4.0 в Kie.ai:
        - prompt
        - image_urls
        - image_size
        - image_resolution
        - max_images
        - seed
        """
        payload: dict[str, t.Any] = {
            "prompt": prompt,
            "image_urls": image_urls,
            "image_size": image_size,
            "image_resolution": image_resolution,
            "max_images": max_images,
        }
        if seed is not None:
            payload["seed"] = seed

        return self._post(SEEDREAM_GENERATE_ENDPOINT, payload)

    def create_task_text_to_image(
        self,
        prompt: str,
        image_size: str = "Portrait 3:4",
        image_resolution: str = "4K",
        max_images: int = 1,
        seed: t.Optional[int] = None,
    ) -> dict:
        """
        Пример text-to-image (Seedream V4 Text To Image).
        В зависимости от реального API, тело может немного отличаться.
        """
        payload: dict[str, t.Any] = {
            "prompt": prompt,
            "image_size": image_size,
            "image_resolution": image_resolution,
            "max_images": max_images,
        }
        if seed is not None:
            payload["seed"] = seed

        return self._post(SEEDREAM_GENERATE_ENDPOINT, payload)

    def get_task_info(self, task_id: str) -> dict:
        """
        Возвращает детали задачи.
        Для большинства моделей Kie.ai путь record-info имеет параметр taskId.
        """
        params = {"taskId": task_id}
        return self._get(SEEDREAM_RECORD_INFO_ENDPOINT, params)

    def wait_for_result(
        self,
        task_id: str,
        poll_interval: float = 5.0,
        timeout: float = 180.0,
    ) -> dict:
        """
        Ожидает завершения задачи по taskId, периодически опрашивая record-info.
        Возвращает финальный JSON (обычно в нём есть resultUrls/resultUrl).
        """
        start = time.time()
        while True:
            data = self.get_task_info(task_id)
            status = (
                data.get("data", {}).get("status")
                or data.get("data", {}).get("taskStatus")
            )
            if status in ("completed", "success", "SUCCESS"):
                print(f"[wait_for_result] task {task_id} completed")
                return data

            if status in ("failed", "error", "ERROR"):
                raise RuntimeError(f"Task {task_id} failed: {data}")

            if time.time() - start > timeout:
                raise TimeoutError(f"Task {task_id} timeout: last data={data}")

            print(f"[wait_for_result] task {task_id} status={status}, sleep {poll_interval}s")
            time.sleep(poll_interval)


# === Вспомогательные функции для сборки промптов из ТЗ ===

def build_base_prompt(
    gender: str,
    hair_color: str,
    age: str,
    style: str,
    background: str,
) -> str:
    """
    Шаблон базового промпта из ТЗ:
    Create a photo of a beautiful [gender] [hair color] [age] model wearing those clothes.
    Keep those clothes as close to their original photo as possible.
    Make it look like a professional [style] photo for e-commerce. [background]
    """
    return (
        f"Create a photo of a beautiful {gender} {hair_color} {age} model wearing those clothes. "
        f"Keep those clothes as close to their original photo as possible. "
        f"Make it look like a professional {style} photo for e-commerce. {background}"
    )


# === Сценарии тестов по ТЗ ===

def scenario_1_initial_generation(client: SeedreamClient, cloth_url: str) -> str:
    """
    Сценарий 1: Базовая генерация каталожного фото из одного фото одежды.
    Возвращает taskId.
    """
    prompt = build_base_prompt(
        gender="female",
        hair_color="blonde",
        age="young adult",
        style="casual",
        background="Beige studio background",
    )

    resp = client.create_task_edit(
        prompt=prompt,
        image_urls=[cloth_url],
        image_size="Portrait 3:4",
        image_resolution="4K",
        max_images=2,
    )
    task_id = resp.get("data", {}).get("taskId")
    print(f"[scenario_1] task_id={task_id}")
    return task_id


def scenario_2_regenerate_same_settings(
    client: SeedreamClient, cloth_url: str
) -> str:
    """
    Сценарий 2: 'Переделать' с теми же настройками.
    По сути, повторяем тот же запрос с тем же промптом.
    """
    prompt = build_base_prompt(
        gender="female",
        hair_color="blonde",
        age="young adult",
        style="casual",
        background="Beige studio background",
    )

    resp = client.create_task_edit(
        prompt=prompt,
        image_urls=[cloth_url],
        image_size="Portrait 3:4",
        image_resolution="4K",
        max_images=1,
    )
    task_id = resp.get("data", {}).get("taskId")
    print(f"[scenario_2] task_id={task_id}")
    return task_id


def scenario_3_regenerate_new_settings(
    client: SeedreamClient, cloth_url: str
) -> str:
    """
    Сценарий 3: 'Переделать с новыми настройками' — меняем часть параметров.
    """
    prompt = build_base_prompt(
        gender="male",
        hair_color="brunette",
        age="young adult",
        style="streetwear",
        background="Urban outdoor background",
    )

    resp = client.create_task_edit(
        prompt=prompt,
        image_urls=[cloth_url],
        image_size="Portrait 2:3",
        image_resolution="4K",
        max_images=2,
    )
    task_id = resp.get("data", {}).get("taskId")
    print(f"[scenario_3] task_id={task_id}")
    return task_id


def scenario_4_change_pose_once(client: SeedreamClient, base_model_url: str) -> str:
    """
    Сценарий 4: Сменить позу один раз (Change pose).
    """
    resp = client.create_task_edit(
        prompt="Change pose",
        image_urls=[base_model_url],
        max_images=1,
    )
    task_id = resp.get("data", {}).get("taskId")
    print(f"[scenario_4] task_id={task_id}")
    return task_id


def scenario_5_change_pose_five(client: SeedreamClient, base_model_url: str) -> str:
    """
    Сценарий 5: Сменить позу 5 раз.
    """
    resp = client.create_task_edit(
        prompt="Change pose",
        image_urls=[base_model_url],
        max_images=5,
    )
    task_id = resp.get("data", {}).get("taskId")
    print(f"[scenario_5] task_id={task_id}")
    return task_id


def scenario_6_change_angle_once(client: SeedreamClient, base_model_url: str) -> str:
    """
    Сценарий 6: Сменить ракурс один раз (Change angle).
    """
    resp = client.create_task_edit(
        prompt="Change angle",
        image_urls=[base_model_url],
        max_images=1,
    )
    task_id = resp.get("data", {}).get("taskId")
    print(f"[scenario_6] task_id={task_id}")
    return task_id


def scenario_7_change_angle_five(client: SeedreamClient, base_model_url: str) -> str:
    """
    Сценарий 7: Сменить ракурс 5 раз.
    """
    resp = client.create_task_edit(
        prompt="Change angle",
        image_urls=[base_model_url],
        max_images=5,
    )
    task_id = resp.get("data", {}).get("taskId")
    print(f"[scenario_7] task_id={task_id}")
    return task_id


def scenario_8_back_view_no_ref(client: SeedreamClient, base_model_url: str) -> str:
    """
    Сценарий 8: Ракурс сзади без фото сзади.
    """
    resp = client.create_task_edit(
        prompt="Change the pose and angle to a back view",
        image_urls=[base_model_url],
        max_images=1,
    )
    task_id = resp.get("data", {}).get("taskId")
    print(f"[scenario_8] task_id={task_id}")
    return task_id


def scenario_9_back_view_with_ref(
    client: SeedreamClient,
    base_model_url: str,
    cloth_back_url: str,
) -> str:
    """
    Сценарий 9: Ракурс сзади с фото одежды сзади как референсом.
    """
    prompt = (
        "Change the pose and angle to a back view. "
        "Use the second image as a reference for how those clothes look from the back."
    )
    resp = client.create_task_edit(
        prompt=prompt,
        image_urls=[base_model_url, cloth_back_url],
        max_images=1,
    )
    task_id = resp.get("data", {}).get("taskId")
    print(f"[scenario_9] task_id={task_id}")
    return task_id


def scenario_10_full_body(client: SeedreamClient, base_model_url: str) -> str:
    """
    Сценарий 10: В полный рост.
    """
    resp = client.create_task_edit(
        prompt="Change to a full body shot",
        image_urls=[base_model_url],
        max_images=1,
    )
    task_id = resp.get("data", {}).get("taskId")
    print(f"[scenario_10] task_id={task_id}")
    return task_id


def scenario_11_upper_body(client: SeedreamClient, base_model_url: str) -> str:
    """
    Сценарий 11: Верх тела.
    """
    resp = client.create_task_edit(
        prompt="Change to an upper body shot",
        image_urls=[base_model_url],
        max_images=1,
    )
    task_id = resp.get("data", {}).get("taskId")
    print(f"[scenario_11] task_id={task_id}")
    return task_id


def scenario_12_lower_body(client: SeedreamClient, base_model_url: str) -> str:
    """
    Сценарий 12: Низ тела.
    """
    resp = client.create_task_edit(
        prompt="Change to a lower body shot",
        image_urls=[base_model_url],
        max_images=1,
    )
    task_id = resp.get("data", {}).get("taskId")
    print(f"[scenario_12] task_id={task_id}")
    return task_id


def main():
    client = SeedreamClient(api_key=API_KEY)

    # Подставь реальные URL-картинок:
    cloth_front_url = os.getenv("CLOTH_FRONT_URL", "https://example.com/cloth_front.jpg")
    cloth_back_url = os.getenv("CLOTH_BACK_URL", "https://example.com/cloth_back.jpg")
    base_model_url = os.getenv("BASE_MODEL_URL", "https://example.com/base_model.jpg")

    print("=== Scenario 1: Initial generation ===")
    task_1 = scenario_1_initial_generation(client, cloth_front_url)
    if task_1:
        client.wait_for_result(task_1)

    # print("=== Scenario 2: Regenerate same settings ===")
    # task_2 = scenario_2_regenerate_same_settings(client, cloth_front_url)
    # if task_2:
    #     client.wait_for_result(task_2)

    # print("=== Scenario 3: Regenerate with new settings ===")
    # task_3 = scenario_3_regenerate_new_settings(client, cloth_front_url)
    # if task_3:
    #     client.wait_for_result(task_3)

    # # Далее считаем, что у нас уже есть base_model_url
    # print("=== Scenario 4: Change pose once ===")
    # task_4 = scenario_4_change_pose_once(client, base_model_url)
    # if task_4:
    #     client.wait_for_result(task_4)

    # print("=== Scenario 5: Change pose five times ===")
    # task_5 = scenario_5_change_pose_five(client, base_model_url)
    # if task_5:
    #     client.wait_for_result(task_5)

    # print("=== Scenario 6: Change angle once ===")
    # task_6 = scenario_6_change_angle_once(client, base_model_url)
    # if task_6:
    #     client.wait_for_result(task_6)

    # print("=== Scenario 7: Change angle five times ===")
    # task_7 = scenario_7_change_angle_five(client, base_model_url)
    # if task_7:
    #     client.wait_for_result(task_7)

    # print("=== Scenario 8: Back view without reference ===")
    # task_8 = scenario_8_back_view_no_ref(client, base_model_url)
    # if task_8:
    #     client.wait_for_result(task_8)

    # print("=== Scenario 9: Back view with reference ===")
    # task_9 = scenario_9_back_view_with_ref(client, base_model_url, cloth_back_url)
    # if task_9:
    #     client.wait_for_result(task_9)

    # print("=== Scenario 10: Full body shot ===")
    # task_10 = scenario_10_full_body(client, base_model_url)
    # if task_10:
    #     client.wait_for_result(task_10)

    # print("=== Scenario 11: Upper body shot ===")
    # task_11 = scenario_11_upper_body(client, base_model_url)
    # if task_11:
    #     client.wait_for_result(task_11)

    # print("=== Scenario 12: Lower body shot ===")
    # task_12 = scenario_12_lower_body(client, base_model_url)
    # if task_12:
    #     client.wait_for_result(task_12)

    # print("Все сценарии отстреляли. Смотри логи и JSON-ответы выше, там будут taskId и resultUrls/итп.")


if __name__ == "__main__":
    main()
