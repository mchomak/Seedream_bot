# seedream_telegram_scenario.py

import os
import time
import json
import typing as t
from pathlib import Path

import requests


API_KEY = "c2d5c6a1e2082539c22f5dfdedc98005"
# --- Эндпоинты Kie.ai ---

# Seedream jobs API (то же, что в предыдущем сценарии)
CREATE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask"
RECORD_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"

# File Upload API (file-stream-upload) — для загрузки байтов файла
FILE_STREAM_UPLOAD_URL = "https://kieai.redpandaai.co/api/file-stream-upload"

# Common API — чтобы из resultUrl получить прямой download URL
DOWNLOAD_URL_API = "https://api.kie.ai/api/v1/common/download-url"


class SeedreamClient:
    """
    Клиент под Seedream 4.0 на Kie.ai (через jobs/createTask + jobs/recordInfo).
    """

    def __init__(self, api_key: str, timeout: int = 60):
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            }
        )

    def _post_json(self, url: str, payload: dict) -> dict:
        resp = self.session.post(
            url, json=payload, timeout=self.timeout, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        )
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

    def create_task_with_image_urls(
        self,
        prompt: str,
        image_urls: list[str],
        image_size: str = "square_hd",
        image_resolution: str = "1K",
        max_images: int = 1,
        seed: t.Optional[int] = None,
    ) -> str:
        """
        Инпут под Seedream 4.0 с изображениями (image-to-image / edit).
        Модель: bytedance/seedream-v4-text-to-image
        + поле image_urls для редактирования/референса.
        """
        input_payload: dict[str, t.Any] = {
            "prompt": prompt,
            "image_size": image_size,
            "image_resolution": image_resolution,
            "max_images": max_images,
            "image_urls": image_urls,
        }
        if seed is not None:
            input_payload["seed"] = seed

        payload: dict[str, t.Any] = {
            "model": "bytedance/seedream-v4-text-to-image",
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
        params = {"taskId": task_id}
        data = self._get(RECORD_INFO_URL, params)
        if data.get("code") != 200:
            raise RuntimeError(f"recordInfo error: {data}")
        return data

    def wait_for_result(
        self,
        task_id: str,
        poll_interval: float = 5.0,
        timeout: float = 180.0,
    ) -> dict:
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


class KieFileUploadClient:
    """
    Обертка над File Stream Upload:
    POST https://kieai.redpandaai.co/api/file-stream-upload
    Поля:
      - file: бинарник
      - uploadPath: путь в хранилище (логический)
      - fileName: имя файла
    Ответ:
      data.downloadUrl — URL, который можно пихать в image_urls.
    """

    def __init__(self, api_key: str, timeout: int = 60):
        self.api_key = api_key
        self.timeout = timeout

    def upload_image_bytes(
        self,
        file_bytes: bytes,
        file_name: str,
        upload_path: str = "images/user-uploads",
    ) -> dict:
        files = {
            "file": (file_name, file_bytes, "image/jpeg"),
        }
        data = {
            "uploadPath": upload_path,
            "fileName": file_name,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            # Content-Type multipart/form-data выставит requests сам
        }
        resp = requests.post(
            FILE_STREAM_UPLOAD_URL,
            headers=headers,
            files=files,
            data=data,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        result = resp.json()
        print(f"[FileUpload] {FILE_STREAM_UPLOAD_URL} -> {result}")

        if not result.get("success") or result.get("code") != 200:
            raise RuntimeError(f"File upload error: {result}")

        return result


class KieDownloadClient:
    """
    Клиент для POST /api/v1/common/download-url:
    На вход: исходный URL из resultJson.resultUrls
    На выход: временный прямой download URL.
    """

    def __init__(self, api_key: str, timeout: int = 60):
        self.api_key = api_key
        self.timeout = timeout

    def get_download_url(self, kie_url: str) -> str:
        payload = {"url": kie_url}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        resp = requests.post(
            DOWNLOAD_URL_API,
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        print(f"[DownloadURL] {DOWNLOAD_URL_API} -> {data}")

        if data.get("code") != 200:
            raise RuntimeError(f"download-url error: {data}")

        return data.get("data")

    def download_file_bytes(self, download_url: str) -> bytes:
        resp = requests.get(download_url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.content


def build_edit_prompt(background: str = "Beige studio background") -> str:
    """
    Промпт для кейса "пользователь прислал фото одежды, меняем фон / делаем e-commerce кадр".
    """
    return (
        "Create a professional e-commerce photo from this input image. "
        "Keep the clothes as close to the original as possible, "
        f"place the model in a {background.lower()} with soft studio lighting."
    )


def scenario_edit_from_local_image(image_path: str) -> Path:
    """
    Сценарий "как будто пользователь прислал фото в Telegram":
      1) читаем локальный файл (аналог скачанного из Telegram);
      2) грузим его в Kie через File Stream Upload -> получаем downloadUrl;
      3) передаем этот URL в image_urls Seedream;
      4) ждем результата;
      5) через common/download-url получаем прямой download URL, качаем байты;
      6) сохраняем в outputs/ (в боте вместо этого отправишь байты пользователю).
    """
    upload_client = KieFileUploadClient(api_key=API_KEY)
    seedream_client = SeedreamClient(api_key=API_KEY)
    dl_client = KieDownloadClient(api_key=API_KEY)

    image_path = Path(image_path)
    file_name = image_path.name

    # 1) читаем локальный файл
    file_bytes = image_path.read_bytes()

    # 2) загружаем в Kie
    upload_result = upload_client.upload_image_bytes(
        file_bytes=file_bytes,
        file_name=file_name,
        upload_path="images/telegram-uploads",
    )
    upload_data = upload_result.get("data", {})
    source_image_url = upload_data.get("downloadUrl")
    if not source_image_url:
        raise RuntimeError(f"No downloadUrl in upload result: {upload_result}")

    print("Source image URL for Seedream:", source_image_url)

    # 3) создаем задачу Seedream с image_urls
    prompt = build_edit_prompt()
    task_id = seedream_client.create_task_with_image_urls(
        prompt=prompt,
        image_urls=[source_image_url],
        image_size="square_hd",     # или portrait_4_3 / landscape_4_3 и т.п.
        image_resolution="1K",
        max_images=1,
        seed=42,
    )
    print("Seedream task id:", task_id)

    # 4) ждем результата
    result = seedream_client.wait_for_result(task_id)

    # 5) достаем resultUrls из resultJson
    data = result.get("data", {})
    result_json_str = data.get("resultJson")
    if not result_json_str:
        raise RuntimeError(f"No resultJson in task result: {result}")

    try:
        result_obj = json.loads(result_json_str)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"resultJson is not valid JSON: {result_json_str}") from e

    result_urls = result_obj.get("resultUrls") or []
    if not result_urls:
        raise RuntimeError(f"No resultUrls in resultJson: {result_obj}")

    seedream_file_url = result_urls[0]
    print("Seedream generated file URL:", seedream_file_url)

    # 6) конвертируем в download URL и скачиваем байты
    download_url = dl_client.get_download_url(seedream_file_url)
    print("Download URL:", download_url)

    image_bytes = dl_client.download_file_bytes(download_url)

    # 7) сохраняем локально (для теста)
    outputs_dir = Path("outputs")
    outputs_dir.mkdir(exist_ok=True)
    out_path = outputs_dir / f"seedream_from_{file_name}"
    out_path.write_bytes(image_bytes)

    print("Saved generated image to:", out_path)
    return out_path


if __name__ == "__main__":
    # Для теста: положи тестовый jpg/png рядом и укажи путь
    test_image = "photo_1_2025-12-02_17-17-07.jpg"  # заменишь на реальный путь
    scenario_edit_from_local_image(test_image)
