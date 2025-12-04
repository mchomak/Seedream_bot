# seedream_service.py

import os
import time
import json
import typing as t
from dataclasses import dataclass
from http.client import RemoteDisconnected  # NEW

import requests
from loguru import logger  # NEW
from requests.exceptions import RequestException  # NEW


# --- Константы и настройки API ---

# Seedream jobs API
CREATE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask"
RECORD_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"

# File Upload API (file-stream-upload)
FILE_STREAM_UPLOAD_URL = "https://kieai.redpandaai.co/api/file-stream-upload"

# Common API для получения временного download URL
DOWNLOAD_URL_API = "https://api.kie.ai/api/v1/common/download-url"

# Модель из доки
SEEDREAM_MODEL = "bytedance/seedream-v4-text-to-image"


@dataclass
class GenerationResult:
    """Результат генерации, удобный для использования в боте."""
    task_id: str
    source_image_urls: list[str]
    result_urls: list[str]
    image_bytes_list: list[bytes]


class SeedreamService:
    """
    Единый сервис для работы с Seedream V4 Text To Image и сопутствующими API Kie:
    - jobs/createTask + jobs/recordInfo
    - file-stream-upload
    - common/download-url
    + набор сценариев, соответствующих ТЗ.
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: int = 60,
        max_retries: int = 3,
        backoff_factor: float = 1.5,
    ):
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            }
        )

    # -------------------------------------------------------------------------
    # Низкоуровневые методы (HTTP)
    # -------------------------------------------------------------------------


    def _sleep_backoff(self, attempt: int) -> None:
        """
        Простейший экспоненциальный backoff:
        attempt=1 -> delay=1.5^0=1
        attempt=2 -> 1.5^1=1.5
        attempt=3 -> 1.5^2=2.25 и т.д.
        """
        delay = self.backoff_factor ** (attempt - 1)
        time.sleep(delay)


    def _post_json(self, url: str, payload: dict) -> dict:
        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.post(
                    url,
                    json=payload,
                    timeout=self.timeout,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                logger.debug(
                    "[SeedreamService] POST {url} OK (attempt={attempt})",
                    extra={"url": url, "attempt": attempt, "payload": payload, "resp": data},
                )
                return data

            except (RequestException, RemoteDisconnected) as e:
                last_exc = e
                logger.warning(
                    "[SeedreamService] POST {url} failed (attempt={attempt})",
                    extra={"url": url, "attempt": attempt, "error": repr(e)},
                )
            except ValueError as e:
                # JSON decode error
                last_exc = e
                logger.warning(
                    "[SeedreamService] POST {url} JSON decode failed (attempt={attempt})",
                    extra={"url": url, "attempt": attempt, "error": repr(e)},
                )

            if attempt < self.max_retries:
                self._sleep_backoff(attempt)

        logger.exception(
            "[SeedreamService] POST {url} failed after all retries",
            extra={"url": url, "payload": payload},
        )
        if last_exc:
            raise last_exc
        raise RuntimeError(f"POST {url} failed without explicit exception")


    def _get(self, url: str, params: dict) -> dict:
        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                logger.debug(
                    "[SeedreamService] GET {url} OK (attempt={attempt})",
                    extra={"url": url, "attempt": attempt, "params": params, "resp": data},
                )
                return data

            except (RequestException, RemoteDisconnected) as e:
                last_exc = e
                logger.warning(
                    "[SeedreamService] GET {url} failed (attempt={attempt})",
                    extra={"url": url, "attempt": attempt, "params": params, "error": repr(e)},
                )
            except ValueError as e:
                last_exc = e
                logger.warning(
                    "[SeedreamService] GET {url} JSON decode failed (attempt={attempt})",
                    extra={"url": url, "attempt": attempt, "params": params, "error": repr(e)},
                )

            if attempt < self.max_retries:
                self._sleep_backoff(attempt)

        logger.exception(
            "[SeedreamService] GET {url} failed after all retries",
            extra={"url": url, "params": params},
        )
        if last_exc:
            raise last_exc
        raise RuntimeError(f"GET {url} failed without explicit exception")


    def _post_multipart(
        self,
        url: str,
        *,
        files: dict,
        data: dict,
    ) -> dict:
        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                headers = {"Authorization": f"Bearer {self.api_key}"}
                resp = requests.post(
                    url,
                    headers=headers,
                    files={**files},
                    data={**data},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                result = resp.json()
                logger.debug(
                    "[SeedreamService] POST multipart {url} OK (attempt={attempt})",
                    extra={
                        "url": url,
                        "attempt": attempt,
                        "data": data,
                        "result": result,
                    },
                )
                return result

            except (RequestException, RemoteDisconnected) as e:
                last_exc = e
                logger.warning(
                    "[SeedreamService] POST multipart {url} failed (attempt={attempt})",
                    extra={"url": url, "attempt": attempt, "data": data, "error": repr(e)},
                )
            except ValueError as e:
                last_exc = e
                logger.warning(
                    "[SeedreamService] POST multipart {url} JSON decode failed (attempt={attempt})",
                    extra={"url": url, "attempt": attempt, "data": data, "error": repr(e)},
                )

            if attempt < self.max_retries:
                self._sleep_backoff(attempt)

        logger.exception(
            "[SeedreamService] POST multipart {url} failed after all retries",
            extra={"url": url, "data": data},
        )
        if last_exc:
            raise last_exc
        raise RuntimeError(f"POST multipart {url} failed without explicit exception")


    # -------------------------------------------------------------------------
    # Базовые операции Seedream / Kie
    # -------------------------------------------------------------------------

    def create_task(
        self,
        prompt: str,
        *,
        image_size: str = "square_hd",
        image_resolution: str = "1K",
        max_images: int = 1,
        seed: int | None = None,
        image_urls: list[str] | None = None,
    ) -> str:
        """
        POST /api/v1/jobs/createTask
        Универсальный метод: text-to-image (без image_urls) и image-to-image/edit (с image_urls).
        """
        input_payload: dict[str, t.Any] = {
            "prompt": prompt,
            "image_size": image_size,
            "image_resolution": image_resolution,
            "max_images": max_images,
        }
        if seed is not None:
            input_payload["seed"] = seed
        if image_urls:
            input_payload["image_urls"] = image_urls

        payload: dict[str, t.Any] = {
            "model": SEEDREAM_MODEL,
            "input": input_payload,
        }

        data = self._post_json(CREATE_TASK_URL, payload)
        if data.get("code") != 200:
            raise RuntimeError(f"CreateTask error: {data}")

        task_id = data.get("data", {}).get("taskId")
        if not task_id:
            raise RuntimeError(f"taskId not found in response: {data}")
        return task_id

    def get_task_info(self, task_id: str) -> dict:
        """
        GET /api/v1/jobs/recordInfo?taskId=...
        """
        params = {"taskId": task_id}
        data = self._get(RECORD_INFO_URL, params)
        if data.get("code") != 200:
            raise RuntimeError(f"recordInfo error: {data}")
        return data

    def wait_for_result(
        self,
        task_id: str,
        *,
        poll_interval: float = 5.0,
        timeout: float = 180.0,
    ) -> dict:
        """
        Поллинг до state == 'success' или 'fail'.
        data.state: 'waiting' | 'success' | 'fail'
        data.resultJson: строка JSON с resultUrls и т.п.
        """
        start = time.time()
        while True:
            data = self.get_task_info(task_id)
            state = data.get("data", {}).get("state")
            print(f"[wait_for_result] task={task_id} state={state}")

            if state == "success":
                print(f"[wait_for_result] task {task_id} completed successfully")
                return data

            if state == "fail":
                raise RuntimeError(f"Task {task_id} failed: {data}")

            if time.time() - start > timeout:
                raise TimeoutError(f"Task {task_id} timeout: last data={data}")

            time.sleep(poll_interval)

    def upload_image_bytes(
        self,
        file_bytes: bytes,
        file_name: str,
        upload_path: str = "images/telegram-uploads",
    ) -> str:
        """
        POST https://kieai.redpandaai.co/api/file-stream-upload
        Возвращает downloadUrl, который можно использовать как image_urls.
        """
        files = {
            "file": (file_name, file_bytes, "image/jpeg"),
        }
        data = {
            "uploadPath": upload_path,
            "fileName": file_name,
        }

        result = self._post_multipart(
            FILE_STREAM_UPLOAD_URL,
            files=files,
            data=data,
        )

        if not result.get("success") or result.get("code") != 200:
            raise RuntimeError(f"File upload error: {result}")

        download_url = result.get("data", {}).get("downloadUrl")
        if not download_url:
            raise RuntimeError(f"No downloadUrl in upload result: {result}")
        return download_url

    def get_download_url(self, kie_url: str) -> str:
        """
        POST /api/v1/common/download-url
        На вход — resultUrl из resultJson, на выход — временный прямой download URL.
        """
        payload = {"url": kie_url}
        data = self._post_json(DOWNLOAD_URL_API, payload)
        if data.get("code") != 200:
            raise RuntimeError(f"download-url error: {data}")

        download_url = data.get("data")
        if not download_url:
            raise RuntimeError(f"No download URL in response: {data}")
        return download_url


    def download_file_bytes(self, download_url: str) -> bytes:
        """
        Скачиваем байты по download URL (из common/download-url) с ретраями.
        """
        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.get(download_url, timeout=self.timeout)
                resp.raise_for_status()
                logger.debug(
                    "[SeedreamService] download_file_bytes OK (attempt={attempt})",
                    extra={"url": download_url, "attempt": attempt},
                )
                return resp.content

            except (RequestException, RemoteDisconnected) as e:
                last_exc = e
                logger.warning(
                    "[SeedreamService] download_file_bytes failed (attempt={attempt})",
                    extra={"url": download_url, "attempt": attempt, "error": repr(e)},
                )

            if attempt < self.max_retries:
                self._sleep_backoff(attempt)

        logger.exception(
            "[SeedreamService] download_file_bytes failed after all retries",
            extra={"url": download_url},
        )
        if last_exc:
            raise last_exc
        raise RuntimeError("download_file_bytes failed without explicit exception")


    # -------------------------------------------------------------------------
    # Хэлперы для промптов под ТЗ
    # -------------------------------------------------------------------------

    @staticmethod
    def build_ecom_prompt(
        gender: str,
        hair_color: str | None,
        age: str | None,
        style_snippet: str,
        background_snippet: str,
    ) -> str:
        """
        Шаблон из ТЗ:
        Create a photo of a beautiful [пол] [цвет волос] [возраст] model wearing those clothes.
        Keep those clothes as close to their original photo as possible.
        Make it look like a professional [Стиль] photo for e-commerce. [фон]
        """
        hair = f"{hair_color} " if hair_color else ""
        age_str = f"{age} " if age else ""
        return (
            f"Create a photo of a beautiful {gender} {hair}{age_str}model wearing those clothes. "
            "Keep those clothes as close to their original photo as possible. "
            f"Make it look like a professional {style_snippet} photo for e-commerce. "
            f"{background_snippet}"
        )

    @staticmethod
    def build_change_pose_prompt() -> str:
        return "Change pose"

    @staticmethod
    def build_change_angle_prompt() -> str:
        return "Change angle"

    @staticmethod
    def build_back_view_prompt(no_back_ref: bool) -> str:
        if no_back_ref:
            return "Change the pose and angle to a back view"
        return (
            "Change the pose and angle to a back view. Use the second image as a "
            "reference for how those clothes look from the back."
        )

    @staticmethod
    def build_full_body_prompt() -> str:
        return "Change to a full body shot"

    @staticmethod
    def build_upper_body_prompt() -> str:
        return "Change to an upper body shot"

    @staticmethod
    def build_lower_body_prompt() -> str:
        return "Change to a lower body shot"

    # -------------------------------------------------------------------------
    # Внутренний хелпер: createTask + wait + скачивание всех resultUrls
    # -------------------------------------------------------------------------

    def _run_and_download(
        self,
        *,
        prompt: str,
        image_urls: list[str] | None,
        image_size: str,
        image_resolution: str,
        max_images: int,
        seed: int | None = None,
    ) -> GenerationResult:
        task_id = self.create_task(
            prompt=prompt,
            image_size=image_size,
            image_resolution=image_resolution,
            max_images=max_images,
            seed=seed,
            image_urls=image_urls,
        )
        task_result = self.wait_for_result(task_id)
        data = task_result.get("data", {})
        result_json_str = data.get("resultJson")
        if not result_json_str:
            raise RuntimeError(f"No resultJson in task result: {task_result}")

        try:
            result_obj = json.loads(result_json_str)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"resultJson is not valid JSON: {result_json_str}"
            ) from e

        result_urls: list[str] = result_obj.get("resultUrls") or []
        if not result_urls:
            raise RuntimeError(f"No resultUrls in resultJson: {result_obj}")

        image_bytes_list: list[bytes] = []
        for url in result_urls:
            download_url = self.get_download_url(url)
            img_bytes = self.download_file_bytes(download_url)
            image_bytes_list.append(img_bytes)

        return GenerationResult(
            task_id=task_id,
            source_image_urls=image_urls or [],
            result_urls=result_urls,
            image_bytes_list=image_bytes_list,
        )

    # -------------------------------------------------------------------------
    # Высокоуровневые сценарии из ТЗ
    # -------------------------------------------------------------------------

    # 1. Базовая генерация из фото одежды пользователя (первая генерация)

    def initial_generation_from_user_photo(
        self,
        *,
        cloth_image_bytes: bytes,
        file_name: str,
        gender: str,
        hair_color: str | None,
        age: str | None,
        style_snippet: str,
        background_snippet: str,
        image_size: str = "portrait_4_3",  # 3:4 из ТЗ
        image_resolution: str = "4K",
        max_images: int = 1,
        seed: int | None = None,
    ) -> GenerationResult:
        """
        Фото одежды (на человеке / манекене / вешалке) → каталожное фото с моделью.
        Основной сценарий ТЗ.
        """
        cloth_url = self.upload_image_bytes(cloth_image_bytes, file_name)
        prompt = self.build_ecom_prompt(
            gender=gender,
            hair_color=hair_color,
            age=age,
            style_snippet=style_snippet,
            background_snippet=background_snippet,
        )

        return self._run_and_download(
            prompt=prompt,
            image_urls=[cloth_url],
            image_size=image_size,
            image_resolution=image_resolution,
            max_images=max_images,
            seed=seed,
        )

    # 2. «Переделать» с теми же настройками

    def regenerate_same_settings(
        self,
        *,
        cloth_image_bytes: bytes,
        file_name: str,
        original_prompt: str,
        image_size: str = "portrait_4_3",
        image_resolution: str = "4K",
        max_images: int = 1,
        seed: int | None = None,
    ) -> GenerationResult:
        """
        'Переделать' — новый запуск с тем же промптом и тем же инпут-фото.
        """
        cloth_url = self.upload_image_bytes(cloth_image_bytes, file_name)
        return self._run_and_download(
            prompt=original_prompt,
            image_urls=[cloth_url],
            image_size=image_size,
            image_resolution=image_resolution,
            max_images=max_images,
            seed=seed,
        )

    # 3. «Переделать с новыми настройками»

    def regenerate_new_settings(
        self,
        *,
        cloth_image_bytes: bytes,
        file_name: str,
        gender: str,
        hair_color: str | None,
        age: str | None,
        style_snippet: str,
        background_snippet: str,
        image_size: str = "portrait_4_3",
        image_resolution: str = "4K",
        max_images: int = 1,
        seed: int | None = None,
    ) -> GenerationResult:
        """
        'Переделать с новыми настройками' — тот же инпут, новый промпт.
        """
        cloth_url = self.upload_image_bytes(cloth_image_bytes, file_name)
        prompt = self.build_ecom_prompt(
            gender=gender,
            hair_color=hair_color,
            age=age,
            style_snippet=style_snippet,
            background_snippet=background_snippet,
        )
        return self._run_and_download(
            prompt=prompt,
            image_urls=[cloth_url],
            image_size=image_size,
            image_resolution=image_resolution,
            max_images=max_images,
            seed=seed,
        )

    # 4. Позы/ракурсы (этап 6): работаем от базового одобренного кадра (URL из истории)

    def change_pose_once_from_base_url(
        self,
        *,
        base_image_url: str,
        image_size: str,
        image_resolution: str,
    ) -> GenerationResult:
        """Сменить позу один раз."""
        prompt = self.build_change_pose_prompt()
        return self._run_and_download(
            prompt=prompt,
            image_urls=[base_image_url],
            image_size=image_size,
            image_resolution=image_resolution,
            max_images=1,
        )

    def change_pose_five_from_base_url(
        self,
        *,
        base_image_url: str,
        image_size: str,
        image_resolution: str,
    ) -> GenerationResult:
        """Сменить позу 5 раз."""
        prompt = self.build_change_pose_prompt()
        return self._run_and_download(
            prompt=prompt,
            image_urls=[base_image_url],
            image_size=image_size,
            image_resolution=image_resolution,
            max_images=5,
        )

    def change_angle_once_from_base_url(
        self,
        *,
        base_image_url: str,
        image_size: str,
        image_resolution: str,
    ) -> GenerationResult:
        """Сменить ракурс один раз."""
        prompt = self.build_change_angle_prompt()
        return self._run_and_download(
            prompt=prompt,
            image_urls=[base_image_url],
            image_size=image_size,
            image_resolution=image_resolution,
            max_images=1,
        )

    def change_angle_five_from_base_url(
        self,
        *,
        base_image_url: str,
        image_size: str,
        image_resolution: str,
    ) -> GenerationResult:
        """Сменить ракурс 5 раз."""
        prompt = self.build_change_angle_prompt()
        return self._run_and_download(
            prompt=prompt,
            image_urls=[base_image_url],
            image_size=image_size,
            image_resolution=image_resolution,
            max_images=5,
        )

    # 5. Ракурс сзади

    def back_view_no_reference(
        self,
        *,
        base_image_url: str,
        image_size: str,
        image_resolution: str,
    ) -> GenerationResult:
        """
        Вид сзади без фото сзади.
        """
        prompt = self.build_back_view_prompt(no_back_ref=True)
        return self._run_and_download(
            prompt=prompt,
            image_urls=[base_image_url],
            image_size=image_size,
            image_resolution=image_resolution,
            max_images=1,
        )

    def back_view_with_reference(
        self,
        *,
        base_image_url: str,
        back_cloth_image_bytes: bytes,
        back_file_name: str,
        image_size: str,
        image_resolution: str,
    ) -> GenerationResult:
        """
        Вид сзади с фото одежды сзади как референсом:
        image_urls = [base_image_url, back_cloth_url]
        """
        back_url = self.upload_image_bytes(back_cloth_image_bytes, back_file_name)
        prompt = self.build_back_view_prompt(no_back_ref=False)
        return self._run_and_download(
            prompt=prompt,
            image_urls=[base_image_url, back_url],
            image_size=image_size,
            image_resolution=image_resolution,
            max_images=1,
        )

    # 6. Фрейминг: полный рост / верх / низ

    def full_body_from_base_url(
        self,
        *,
        base_image_url: str,
        image_size: str,
        image_resolution: str,
    ) -> GenerationResult:
        """В полный рост."""
        prompt = self.build_full_body_prompt()
        return self._run_and_download(
            prompt=prompt,
            image_urls=[base_image_url],
            image_size=image_size,
            image_resolution=image_resolution,
            max_images=1,
        )

    def upper_body_from_base_url(
        self,
        *,
        base_image_url: str,
        image_size: str,
        image_resolution: str,
    ) -> GenerationResult:
        """Верх тела."""
        prompt = self.build_upper_body_prompt()
        return self._run_and_download(
            prompt=prompt,
            image_urls=[base_image_url],
            image_size=image_size,
            image_resolution=image_resolution,
            max_images=1,
        )

    def lower_body_from_base_url(
        self,
        *,
        base_image_url: str,
        image_size: str,
        image_resolution: str,
    ) -> GenerationResult:
        """Низ тела."""
        prompt = self.build_lower_body_prompt()
        return self._run_and_download(
            prompt=prompt,
            image_urls=[base_image_url],
            image_size=image_size,
            image_resolution=image_resolution,
            max_images=1,
        )


# Опционально: быстрая ручная проверка
if __name__ == "__main__":
    from pathlib import Path

    service = SeedreamService()
    test_path = Path("user_photo.jpg")
    if test_path.exists():
        b = test_path.read_bytes()
        res = service.initial_generation_from_user_photo(
            cloth_image_bytes=b,
            file_name=test_path.name,
            gender="female",
            hair_color="blonde",
            age="young adult",
            style_snippet="casual fashion brand style",
            background_snippet="Beige studio background",
            image_size="portrait_4_3",
            image_resolution="4K",
            max_images=1,
            seed=42,
        )
        out_dir = Path("outputs")
        out_dir.mkdir(exist_ok=True)
        for i, img in enumerate(res.image_bytes_list, start=1):
            p = out_dir / f"seedream_test_{i}.png"
            p.write_bytes(img)
            print("Saved:", p)
    else:
        print("Put user_photo.jpg near this file to test.")
