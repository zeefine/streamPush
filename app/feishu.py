from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import get_env_settings, load_file_settings

logger = logging.getLogger(__name__)


async def get_tenant_access_token() -> str:
    env = get_env_settings()
    cfg = load_file_settings()
    endpoint = f"{cfg['feishu']['base_url'].rstrip('/')}/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": env.feishu_app_id, "app_secret": env.feishu_app_secret}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(endpoint, json=payload)
        resp.raise_for_status()
        data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(f"Failed to get tenant token: {data}")
    logger.info("feishu_token_acquired")
    return data["tenant_access_token"]


def resolve_recipient() -> tuple[str, str]:
    env = get_env_settings()
    cfg = load_file_settings()["feishu"]
    id_type = cfg.get("recipient_id_type", "chat_id")
    if id_type == "open_id":
        if not env.feishu_open_id:
            raise RuntimeError("recipient_id_type=open_id but FEISHU_OPEN_ID is empty")
        return id_type, env.feishu_open_id
    if not env.feishu_chat_id:
        raise RuntimeError("recipient_id_type=chat_id but FEISHU_CHAT_ID is empty")
    return "chat_id", env.feishu_chat_id


async def send_text_message(text: str) -> dict[str, Any]:
    cfg = load_file_settings()["feishu"]
    endpoint = f"{cfg['base_url'].rstrip('/')}/open-apis/im/v1/messages"
    recipient_id_type, receive_id = resolve_recipient()

    token = await get_tenant_access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            endpoint,
            params={"receive_id_type": recipient_id_type},
            headers=headers,
            json=payload,
        )
        try:
            data = resp.json()
        except Exception:
            data = {"raw_text": resp.text}

    if resp.status_code >= 400:
        raise RuntimeError(
            "Feishu HTTP error when sending message: "
            f"status={resp.status_code}, receive_id_type={recipient_id_type}, "
            f"receive_id={receive_id}, response={data}"
        )
    if data.get("code") != 0:
        raise RuntimeError(
            "Feishu API error when sending message: "
            f"code={data.get('code')}, msg={data.get('msg')}, "
            f"receive_id_type={recipient_id_type}, receive_id={receive_id}, response={data}"
        )
    logger.info(
        "feishu_message_sent receive_id_type=%s receive_id=%s message_id=%s text_chars=%s",
        recipient_id_type,
        receive_id,
        data.get("data", {}).get("message_id"),
        len(text),
    )
    return data
