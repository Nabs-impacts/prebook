import hashlib

from fastapi import Request, Response


def build_etag(body: str) -> str:
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f'"{digest}"'


def conditional_json_response(
    request: Request,
    body: str,
    cache_control: str,
) -> Response:
    etag = build_etag(body)
    headers = {"Cache-Control": cache_control, "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)
