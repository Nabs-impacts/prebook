from fastapi import Request


def client_ip(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host
