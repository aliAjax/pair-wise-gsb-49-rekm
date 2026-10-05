import tempfile
import unittest
from pathlib import Path

from app import build_service
from src.domain import Actor, Conflict, PermissionDenied
from tests.helpers import CREATE_DATA, ORG_A, seed_admin, seed_team


class FailureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = build_service(str(Path(self.temp.name) / "test.db"))
        self.team = seed_team(self.service)
        self.admin = seed_admin(self.service)

    def tearDown(self):
        self.temp.cleanup()

    def test_unknown_identity_rejected(self):
        # 身份目录未登记的用户，自报角色也无效
        with self.assertRaises(PermissionDenied):
            self.service.create(Actor("ghost", "underwriter", ORG_A), "RI-25001", CREATE_DATA)

    def test_permission_and_duplicate(self):
        with self.assertRaises(PermissionDenied):
            self.service.create(self.team["claims"], "RI-25001", CREATE_DATA)
        self.service.create(self.team["underwriter"], "RI-25001", CREATE_DATA)
        with self.assertRaises(Conflict):
            self.service.create(self.team["underwriter"], "RI-25001", CREATE_DATA)

    def test_stale_version_is_rejected(self):
        record = self.service.create(self.team["underwriter"], "RI-25001", CREATE_DATA)
        record = self.service.act(self.team["underwriter"], record["id"], record["version"], "bind", {"underwriter_id": "UW-8"})
        with self.assertRaises(Conflict):
            self.service.act(self.team["claims"], record["id"], record["version"] - 1, "submit_claim", {"claim_number": "CLM-88", "event_id": "CAT-2026-01"})
