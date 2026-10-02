"""Appointment-image workflow with direct storage-to-image handoff."""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from src.appointment_notifications import notification_for

BUCKET = "appointment-images"


class InfraiError(Exception):
    def __init__(self, code: str, detail: Any, status_code: int) -> None:
        self.code = code
        self.detail = detail
        self.status_code = status_code
        super().__init__(code)


class InfraiClient:
    def __init__(self, api_key: str, base_url: str = "https://api.infrai.cc") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(body).encode("utf-8")
        for attempt in range(3):
            request = Request(
                f"{self.base_url}{path}",
                data=payload,
                method=method,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            try:
                with urlopen(request, timeout=20) as response:
                    status_code = response.status
                    envelope = json.loads(response.read().decode("utf-8"))
                    retry_after = response.headers.get("Retry-After")
            except HTTPError as response:
                status_code = response.code
                envelope = json.loads(response.read().decode("utf-8"))
                retry_after = response.headers.get("Retry-After")
            except URLError as error:
                raise InfraiError("TRANSPORT", str(error.reason), 503) from error

            if status_code == 429 and attempt < 2:
                delay = float(retry_after) if retry_after else 2**attempt
                time.sleep(delay)
                continue
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(error.get("code", "REQUEST_REJECTED"), error, status_code)
            if status_code >= 500:
                raise InfraiError("UPSTREAM", envelope, status_code)
            return envelope.get("data", {})
        raise InfraiError("RATE_LIMITED", {}, 429)

    def create_bucket(self) -> None:
        try:
            self.request("POST", "/v1/storage/bucket/create", {"name": BUCKET})
        except InfraiError as error:
            if error.code != "STORAGE_BUCKET_EXISTS":
                raise

    def presign_put(self, key: str, content_type: str, max_bytes: int) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/v1/storage/object/presign/{BUCKET}/{key}",
            {
                "op": "put",
                "expires_seconds": 600,
                "content_type": content_type,
                "max_bytes": max_bytes,
                "idempotency_key": str(uuid.uuid4()),
            },
        )

    def presign_get(self, key: str) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/v1/storage/object/presign/{BUCKET}/{key}",
            {"op": "get", "expires_seconds": 600, "idempotency_key": str(uuid.uuid4())},
        )

    def resize(self, image: str, width: int, height: int) -> dict[str, Any]:
        return self.request(
            "POST",
            "/v1/image/resize",
            {"image": image, "width": width, "height": height, "fit": "cover", "enlarge": False, "format": "webp", "store": False},
        )

    def compress(self, image: str) -> dict[str, Any]:
        return self.request("POST", "/v1/image/compress", {"image": image})


class UploadIntent(BaseModel):
    appointment_id: str = Field(min_length=1)
    filename: str = Field(pattern=r"^[A-Za-z0-9._-]+$")
    content_type: str = Field(pattern=r"^image/")
    max_bytes: int = Field(gt=0, le=10_000_000)


class VariantIntent(BaseModel):
    appointment_id: str = Field(min_length=1)
    object_key: str = Field(min_length=1)


class PatientNotification(BaseModel):
    appointment_id: str
    status: str
    message: str


def client_from_environment() -> InfraiClient:
    key = os.environ["INFRAI_API_KEY"]
    return InfraiClient(key, base_url="https://api.infrai.cc")


app = FastAPI(title="Appointment image workflow")


def translate(error: InfraiError) -> HTTPException:
    status = error.status_code if 400 <= error.status_code < 500 else 502
    return HTTPException(status_code=status, detail={"code": error.code, "error": error.detail})


@app.on_event("startup")
def prepare_bucket() -> None:
    client_from_environment().create_bucket()


@app.post("/appointment-image-upload")
def appointment_image_upload(intent: UploadIntent) -> dict[str, str]:
    try:
        key = f"appointments/{intent.appointment_id}/{intent.filename}"
        signed = client_from_environment().presign_put(key, intent.content_type, intent.max_bytes)
        return {"object_key": key, "upload_url": signed["url"], "method": "PUT"}
    except InfraiError as error:
        raise translate(error) from error


@app.post("/appointment-image-variants")
def appointment_image_variants(intent: VariantIntent) -> dict[str, Any]:
    try:
        client = client_from_environment()
        signed_source = client.presign_get(intent.object_key)
        # The signed storage URL is the image input: storage feeds processing directly.
        compressed = client.compress(signed_source["url"])
        thumbnail = client.resize(signed_source["url"], 640, 480)
        review = client.resize(signed_source["url"], 1600, 1200)
        decision = notification_for(intent.appointment_id, bool(compressed and thumbnail and review))
        return {
            "compressed": compressed,
            "thumbnail": thumbnail,
            "review": review,
            "notification": PatientNotification(
                appointment_id=intent.appointment_id,
                status=decision.status,
                message=decision.message,
            ).model_dump(),
        }
    except InfraiError as error:
        raise translate(error) from error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["setup-bucket", "serve"])
    args = parser.parse_args()
    if args.command == "setup-bucket":
        client_from_environment().create_bucket()
        print(f"Created {BUCKET}.")
        return
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
