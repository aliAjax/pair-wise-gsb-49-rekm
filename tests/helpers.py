"""测试共享常量与用户登记工具。"""
from src.domain import Actor

ORG_A = "华东分公司"
ORG_B = "华南分公司"
HQ_ORG = "总部"

CREATE_DATA = {'event_id': 'CAT-2026-01', 'attachment': 1000000.0, 'limit': 5000000.0, 'cession_pct': 0.4, 'loss_amount': 3000000.0, 'reinstatement_pct': 0.15, 'aggregate_prior': 0.0}
# 摊回金额=1900万*0.5=950万，超过500万复核线
BIG_CREATE_DATA = {'event_id': 'CAT-2026-99', 'attachment': 1000000.0, 'limit': 20000000.0, 'cession_pct': 0.5, 'loss_amount': 20000000.0, 'reinstatement_pct': 0.1, 'aggregate_prior': 0.0}


def register(service, user_id, role, org=ORG_A):
    service.repository.upsert_user(user_id, role, org)
    return Actor(user_id, role, org)


def seed_team(service, org=ORG_A, suffix=""):
    return {
        "underwriter": register(service, "uw-1" + suffix, "underwriter", org),
        "claims": register(service, "claims-1" + suffix, "claims_officer", org),
        "finance": register(service, "fin-1" + suffix, "finance", org),
        "finance2": register(service, "fin-2" + suffix, "finance", org),
    }


def seed_admin(service, user_id="hq-admin"):
    return register(service, user_id, "admin", HQ_ORG)
