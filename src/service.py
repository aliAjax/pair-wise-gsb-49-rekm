"""业务用例编排、权限检查与审计。"""
from typing import Any, Dict, List, Optional

from .audit import AuditRecorder
from .domain import HQ_ORG, UNASSIGNED_ORG, Actor, Conflict, PermissionDenied, ValidationError, text
from .repository import Repository
from .rules import DomainRules


# 待分配赔案在补全归属前禁止推进的资金类动作。
ASSIGN_GATED_ACTIONS = {"calculate", "settle"}


class Service:
    def __init__(self, repository: Repository, rules: DomainRules, audit: AuditRecorder = None) -> None:
        self.repository = repository
        self.rules = rules
        self.audit = audit or AuditRecorder(repository)

    @staticmethod
    def _actor(actor: Actor) -> Actor:
        if actor is None or not actor.user_id.strip() or not actor.role.strip():
            raise PermissionDenied("缺少调用身份")
        return actor

    def _ensure_known_role(self, actor: Actor) -> None:
        if not self.rules.known_role(actor.role):
            raise PermissionDenied("角色无权访问该服务")

    @staticmethod
    def _is_hq_admin(actor: Actor) -> bool:
        return actor.role == "admin" and actor.organization == HQ_ORG

    def _scope_org(self, actor: Actor) -> Optional[str]:
        """返回调用者可见的分公司；总公司管理员返回None表示全部。"""
        if self._is_hq_admin(actor):
            return None
        if not actor.organization:
            raise PermissionDenied("身份缺少分公司归属")
        return actor.organization

    def _ensure_visible(self, actor: Actor, record: Dict[str, Any]) -> None:
        if self._is_hq_admin(actor):
            return
        if not actor.organization or record["org"] != actor.organization:
            raise PermissionDenied("无权访问其他分公司赔案")

    def create(self, actor: Actor, reference: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._actor(actor)
        self._ensure_known_role(actor)
        if not self.rules.role_can_create(actor.role):
            raise PermissionDenied("角色无权创建记录")
        if not actor.organization or actor.organization == HQ_ORG:
            raise PermissionDenied("录单身份必须归属分公司")
        reference = text({"reference": reference}, "reference")
        prepared = self.rules.prepare_create(payload or {})
        prepared.pop("org", None)
        self.rules.check_create_conflicts(prepared, self.repository.list_records(limit=500))
        return self.repository.create(reference, self.rules.INITIAL_STATE, prepared, actor.user_id, actor.organization)

    def list_records(self, actor: Actor, state: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        actor = self._actor(actor)
        self._ensure_known_role(actor)
        return self.repository.list_records(state=state, limit=limit, org=self._scope_org(actor))

    def get_record(self, actor: Actor, record_id: int) -> Dict[str, Any]:
        actor = self._actor(actor)
        self._ensure_known_role(actor)
        record = self.repository.get(record_id)
        self._ensure_visible(actor, record)
        return record

    def act(self, actor: Actor, record_id: int, expected_version: int, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
        actor = self._actor(actor)
        self._ensure_known_role(actor)
        action = text({"action": action}, "action")
        if not self.rules.role_can_action(actor.role, action):
            raise PermissionDenied("角色无权执行该操作")
        record = self.repository.get(record_id)
        self._ensure_visible(actor, record)
        self.rules.require_transition(record, action)
        if record["org"] == UNASSIGNED_ORG and action in ASSIGN_GATED_ACTIONS:
            raise Conflict("赔案尚未分配分公司，补全前不能核定或结算")
        new_state, new_payload, summary = self.rules.apply_action(record, action, data or {}, actor)
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
        actor = self._actor(actor)
        self._ensure_known_role(actor)
        if not self._is_hq_admin(actor):
            raise PermissionDenied("仅总公司管理员可查看待分配队列")
        return self.repository.list_records(org=UNASSIGNED_ORG, limit=limit)

    def assign_org(self, actor: Actor, record_id: int, org: str, expected_version: int) -> Dict[str, Any]:
        actor = self._actor(actor)
        self._ensure_known_role(actor)
        if not self._is_hq_admin(actor):
            raise PermissionDenied("仅总公司管理员可补全分公司归属")
        org = text({"org": org}, "org")
        if org == HQ_ORG:
            raise ValidationError("赔案必须归属到分公司")
        return self.repository.assign_org(record_id, int(expected_version), org, actor.user_id)

    def timeline(self, actor: Actor, record_id: int) -> List[Dict[str, Any]]:
        actor = self._actor(actor)
        self._ensure_known_role(actor)
        record = self.repository.get(record_id)
        self._ensure_visible(actor, record)
        return self.audit.timeline(record_id)

    def stats(self, actor: Actor) -> Dict[str, int]:
        actor = self._actor(actor)
        self._ensure_known_role(actor)
        return self.repository.stats(org=self._scope_org(actor))
