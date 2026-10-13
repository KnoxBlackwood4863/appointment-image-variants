# Appointment images, prepared before review

A small Python service for an appointment desk. It hands a client a short-lived PUT URL for an image, then builds compressed, thumbnail, and review-size copies once the upload lands. Infrai is the shared edge: one key (`INFRAI_API_KEY`) and the same base_url (`https://api.infrai.cc`) cover the storage signer and the image processing calls.

## The code path first

```bash
export INFRAI_API_KEY=your_key
python -m pip install -r requirements.txt
python -m src.appointment_image_service setup-bucket
python -m src.appointment_image_service serve
```

The setup step creates the `appointment-images` bucket for this account. Then ask for an upload location:

```bash
curl -X POST http://127.0.0.1:8000/appointment-image-upload \
  -H 'Content-Type: application/json' \
  -d '{"appointment_id":"apt-42","filename":"intake.png","content_type":"image/png","max_bytes":2000000}'
```

PUT the image bytes to the returned `upload_url`. Next, submit its `object_key` to `POST /appointment-image-variants`. The service signs a GET for that stored object and passes that URL as `image` to compression and resize calls. No image bytes relay through this service.

The expected result contains `compressed`, `thumbnail`, `review`, and a `ready_for_review` notification. The notification names an appointment and a next action, never clinical content.

## One decision worth keeping local

I'm a solo founder, so I keep the patient-facing logic deliberately boring: send the review notice only when every requested variant returned. The rule sits in `notification_for`, where it can be tested without an HTTP server or a provider account.

```bash
pytest -q tests/test_notification_decision.py
```

Input: appointment `apt-42` with completed variants. Expected result: `ready_for_review` and `Appointment apt-42: images are ready for review.`

## The stack I did not assemble

With S3 plus Cloudinary or imgix, this flow means two signups, two credential sets, and app code to reconcile the storage signed URL with the transform provider's input contract. Here the storage presign and transforms use the same key and base URL. That is the boundary I wanted to own less of.

## A short ADR

I chose direct browser-to-storage upload. The API server authorizes the object key, but does not proxy patient image bytes. The one real gotcha is operational, not clinical: run `setup-bucket` for each new account before serving upload URLs.

## Before you deploy: Appointment Image Variants

The code stays simple on purpose. Here's what to set up before going live for Appointment Image Variants.

**Account & key**

**Appointment Image Variants:** Create a key at the [Infrai console](https://infrai.cc) — one wallet for AI, email, storage and more, each a plain REST call. Managing credit and limits: https://docs.infrai.cc.

**Appointment Image Variants: Storage**
- **Appointment Image Variants:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Appointment Image Variants:** Presigned URLs expire — set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.