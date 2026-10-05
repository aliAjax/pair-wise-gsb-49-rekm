import tempfile
import unittest
from pathlib import Path

from app import build_service
from src.domain import PermissionDenied
from tests.helpers import CREATE_DATA, ORG_A, ORG_B, seed_admin, seed_team


class OrgScopeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = build_service(str(Path(self.temp.name) / "test.db"))
        self.team_a = seed_team(self.service, ORG_A, suffix="-a")
        self.team_b = seed_team(self.service, ORG_B, suffix="-b")
        self.admin = seed_admin(self.service)
        self.record_a = self.service.create(self.team_a["underwriter"], "RI-A-1", CREATE_DATA)
        self.record_b = self.service.create(self.team_b["underwriter"], "RI-B-1", CREATE_DATA)

    def tearDown(self):
        self.temp.cleanup()

    def test_create_pins_org_from_identity(self):
        self.assertEqual(self.record_a["org"], ORG_A)
        self.assertEqual(self.record_b["org"], ORG_B)
        spoofed = dict(CREATE_DATA)
        spoofed["org"] = ORG_B  # 客户端伪造归属字段应被忽略
        record = self.service.create(self.team_a["underwriter"], "RI-A-2", spoofed)
        self.assertEqual(record["org"], ORG_A)
        self.assertNotIn("org", record["payload"])

    def test_list_and_stats_are_org_scoped(self):
        items_a = self.service.list_records(self.team_a["claims"])
        self.assertEqual({item["org"] for item in items_a}, {ORG_A})
        ids_a = {item["id"] for item in items_a}
        self.assertIn(self.record_a["id"], ids_a)
        self.assertNotIn(self.record_b["id"], ids_a)
        stats_a = self.service.stats(self.team_a["finance"])
        self.assertEqual(sum(stats_a.values()), len(items_a))
        admin_items = self.service.list_records(self.admin)
        self.assertGreaterEqual(len(admin_items), 2)

    def test_cross_org_detail_audit_and_actions_denied(self):
        with self.assertRaises(PermissionDenied):
            self.service.get_record(self.team_b["claims"], self.record_a["id"])
        with self.assertRaises(PermissionDenied):
            self.service.timeline(self.team_b["claims"], self.record_a["id"])
        with self.assertRaises(PermissionDenied):
            self.service.act(self.team_b["underwriter"], self.record_a["id"], self.record_a["version"], "bind", {"underwriter_id": "UW-9"})
        # 本分公司可以正常操作
        updated = self.service.act(self.team_a["underwriter"], self.record_a["id"], self.record_a["version"], "bind", {"underwriter_id": "UW-9"})
        self.assertEqual(updated["state"], "bound")
