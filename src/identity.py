"""调用方身份目录：用户到角色与分公司的服务端映射。

请求头只携带用户标识，角色与分公司归属由服务端目录解析，
客户端无法通过伪造请求头变更身份或切换分公司。
"""
import json
from pathlib import Path
from typing import Dict, Optional

from .domain import Actor, PermissionDenied


DEFAULT_USERS: Dict[str, Dict[str, str]] = {
    "demo-admin": {"role": "admin", "org": "HQ"},
    "uw-east": {"role": "underwriter", "org": "east"},
    "claims-east": {"role": "claims_officer", "org": "east"},
    "fin-east-a": {"role": "finance", "org": "east"},
    "fin-east-b": {"role": "finance", "org": "east"},
    "uw-west": {"role": "underwriter", "org": "west"},
    "claims-west": {"role": "claims_officer", "org": "west"},
    "fin-west-a": {"role": "finance", "org": "west"},
}


class UserDirectory:
    def __init__(self, users: Optional[Dict[str, Dict[str, str]]] = None) -> None:
        self.users = dict(users or DEFAULT_USERS)

    @classmethod
    def load(cls, path: str) -> "UserDirectory":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("用户目录必须是JSON对象")
        return cls(data)

    def resolve(self, user_id: str) -> Actor:
        entry = self.users.get(user_id)
        if not entry:
            raise PermissionDenied("未知用户，拒绝访问")
        return Actor(
            user_id=user_id,
            role=str(entry.get("role", "")).strip(),
            organization=str(entry.get("org", "")).strip(),
        )
