import tempfile
import unittest
from pathlib import Path

from app import build_service
from src.domain import Conflict, PermissionDenied
from tests.helpers import BIG_CREATE_DATA, CREATE_DATA, seed_admin, seed_team


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = build_service(str(Path(self.temp.name) / "test.db"))
        self.team = seed_team(self.service)
        self.admin = seed_admin(self.service)

    def tearDown(self):
        self.temp.cleanup()

    def _big_claim(self, reference):
        record = self.service.create(self.team["underwriter"], reference, BIG_CREATE_DATA)
        record = self.service.act(self.team["underwriter"], record["id"], record["version"], "bind", {"underwriter_id": "UW-8"})
        record = self.service.act(self.team["claims"], record["id"], record["version"], "submit_claim", {"claim_number": "CLM-99", "event_id": "CAT-2026-99"})
        record = self.service.act(self.team["claims"], record["id"], record["version"], "calculate", {"approved_loss": 20000000.0})
        self.assertGreater(record["payload"]["recoverable_amount"], 5000000.0)
        return record

    def test_over_limit_requires_second_finance_review(self):
        record = self._big_claim("RI-BIG-1")
        # 未复核不能结算
        with self.assertRaises(Conflict):
            self.service.act(self.team["finance"], record["id"], record["version"], "settle", {"payment_reference": "PAY-1"})
        # 复核仅限财务角色，管理员也不能代办
        with self.assertRaises(PermissionDenied):
            self.service.act(self.team["claims"], record["id"], record["version"], "review", {})
        with self.assertRaises(PermissionDenied):
            self.service.act(self.admin, record["id"], record["version"], "review", {})
        record = self.service.act(self.team["finance"], record["id"], record["version"], "review", {})
        self.assertEqual(record["payload"]["reviewed_by"], "fin-1")
        # 复核人不能与结算提交人同号
        with self.assertRaises(PermissionDenied):
            self.service.act(self.team["finance"], record["id"], record["version"], "settle", {"payment_reference": "PAY-1"})
        record = self.service.act(self.team["finance2"], record["id"], record["version"], "settle", {"payment_reference": "PAY-1"})
        self.assertEqual(record["state"], "settled")
        actions = [event["action"] for event in self.service.timeline(self.team["finance"], record["id"])]
        self.assertIn("review", actions)

    def test_concurrent_review_first_writer_wins(self):
        record = self._big_claim("RI-BIG-2")
        version = record["version"]
        first = self.service.act(self.team["finance"], record["id"], version, "review", {})
        self.assertEqual(first["payload"]["reviewed_by"], "fin-1")
        # 同时提交的另一名财务拿到版本冲突
        with self.assertRaises(Conflict):
            self.service.act(self.team["finance2"], record["id"], version, "review", {})
        # 刷新版本后重复复核同样被拒绝
        with self.assertRaises(Conflict):
            self.service.act(self.team["finance2"], record["id"], first["version"], "review", {})

    def test_small_claim_settles_without_review(self):
        record = self.service.create(self.team["underwriter"], "RI-SMALL-1", CREATE_DATA)
        record = self.service.act(self.team["underwriter"], record["id"], record["version"], "bind", {"underwriter_id": "UW-8"})
        record = self.service.act(self.team["claims"], record["id"], record["version"], "submit_claim", {"claim_number": "CLM-1", "event_id": "CAT-2026-01"})
        record = self.service.act(self.team["claims"], record["id"], record["version"], "calculate", {"approved_loss": 2800000.0})
        record = self.service.act(self.team["finance"], record["id"], record["version"], "settle", {"payment_reference": "PAY-2"})
        self.assertEqual(record["state"], "settled")
