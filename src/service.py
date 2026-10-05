"""业务用例编排、权限检查与审计。"""
from typing import Any, Dict, List, Optional

from .audit import AuditRecorder
from .domain import Actor, Conflict, PermissionDenied, text
from .repository import Repository
from .rules import DomainRules


class Service:
    # 归属待分配的赔案在补全前禁止核定与结算
    UNASSIGNED_BLOCKED_ACTIONS = {"calculate", "settle"}

    def __init__(self, repository: Repository, rules: DomainRules, audit: AuditRecorder = None) -> None:
        self.repository = repository
        self.rules = rules
        self.audit = audit or AuditRecorder(repository)

    def _resolve_actor(self, actor: Actor) -> Actor:
        """以服务端身份目录为准解析调用者，客户端自报的角色与分公司一律忽略。"""
        if actor is None or not actor.user_id or not actor.user_id.strip():
            raise PermissionDenied("缺少调用身份")
        user = self.repository.get_user(actor.user_id.strip())
        if user is None:
            raise PermissionDenied("身份未登记")
        resolved = Actor(user_id=user["user_id"], role=user["role"], organization=user["org"])
        if not self.rules.known_role(resolved.role):
            raise PermissionDenied("角色无权访问该服务")
        return resolved

    @staticmethod
    def _ensure_org_access(actor: Actor, record: Dict[str, Any]) -> None:
        if actor.role == "admin":
            return
        org = (record.get("org") or "").strip()
        if not org:
            raise PermissionDenied("赔案分公司归属待分配，仅总公司管理员可处理")
        if org != actor.organization:
            raise PermissionDenied("无权访问其他分公司赔案")

    def create(self, actor: Actor, reference: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._resolve_actor(actor)
        if not self.rules.role_can_create(actor.role):
            raise PermissionDenied("角色无权创建记录")
        reference = text({"reference": reference}, "reference")
        payload = dict(payload or {})
        payload.pop("org", None)  # 归属以身份目录为准，忽略客户端伪造字段
        prepared = self.rules.prepare_create(payload)
        self.rules.check_create_conflicts(prepared, self.repository.list_records(limit=500, org=actor.organization))
        return self.repository.create(reference, self.rules.INITIAL_STATE, prepared, actor.user_id, actor.organization)

    def list_records(self, actor: Actor, state: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        actor = self._resolve_actor(actor)
        org = None if actor.role == "admin" else actor.organization
        return self.repository.list_records(state=state, limit=limit, org=org)

    def get_record(self, actor: Actor, record_id: int) -> Dict[str, Any]:
        actor = self._resolve_actor(actor)
        record = self.repository.get(record_id)
        self._ensure_org_access(actor, record)
        return record

    def act(self, actor: Actor, record_id: int, expected_version: int, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._resolve_actor(actor)
        action = text({"action": action}, "action")
        if not self.rules.role_can_action(actor.role, action):
            raise PermissionDenied("角色无权执行该操作")
        record = self.repository.get(record_id)
        self._ensure_org_access(actor, record)
        if action == self.rules.ASSIGN_ORG_ACTION:
            org = text(data or {}, "org")
            return self.repository.assign_org(record["id"], int(expected_version), org, actor.user_id)
        if not (record.get("org") or "").strip() and action in self.UNASSIGNED_BLOCKED_ACTIONS:
            raise Conflict("赔案分公司归属待分配，补全前不能核定或结算")
        self.rules.require_transition(record, action)
        new_state, new_payload, summary = self.rules.apply_action(record, action, data or {}, actor_id=actor.user_id)
        return self.repository.mutate(
            record_id=record_id,
            expected_version=int(expected_version),
            state=new_state,
            payload=new_payload,
            actor_id=actor.user_id,
            action=action,
            details={"summary": summary, "input": data or {}, "from": record["state"], "to": new_state},
        )

    def pending_assignments(self, actor: Actor, limit: int = 100) -> List[Dict[str, Any]]:
        actor = self._resolve_actor(actor)
        if actor.role != "admin":
            raise PermissionDenied("仅总公司管理员可查看待分配队列")
        return self.repository.list_unassigned(limit=limit)

    def timeline(self, actor: Actor, record_id: int) -> List[Dict[str, Any]]:
        actor = self._resolve_actor(actor)
        record = self.repository.get(record_id)
        self._ensure_org_access(actor, record)
        return self.audit.timeline(record_id)

    def stats(self, actor: Actor) -> Dict[str, int]:
        actor = self._resolve_actor(actor)
        org = None if actor.role == "admin" else actor.organization
        return self.repository.stats(org=org)
