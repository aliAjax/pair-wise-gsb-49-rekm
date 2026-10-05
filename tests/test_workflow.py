import tempfile
import unittest
from pathlib import Path

from app import build_service
from tests.helpers import CREATE_DATA, ORG_A, seed_admin, seed_team


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = build_service(str(Path(self.temp.name) / "test.db"))
        self.team = seed_team(self.service)
        self.admin = seed_admin(self.service)

    def tearDown(self):
        self.temp.cleanup()

    def test_complete_workflow_and_audit(self):
        record = self.service.create(self.team["underwriter"], "RI-25001", CREATE_DATA)
        self.assertEqual(record["state"], "quoted")
        self.assertEqual(record["org"], ORG_A)
        flow = [
            ("bind", self.team["underwriter"], {"underwriter_id": "UW-8"}, "bound"),
            ("submit_claim", self.team["claims"], {"claim_number": "CLM-88", "event_id": "CAT-2026-01"}, "claim_submitted"),
            ("calculate", self.team["claims"], {"approved_loss": 2800000.0}, "calculated"),
            ("settle", self.team["finance"], {"payment_reference": "PAY-1"}, "settled"),
        ]
        for action, actor, data, expected_state in flow:
            record = self.service.act(actor, record["id"], record["version"], action, data)
            self.assertEqual(record["state"], expected_state)
        timeline = self.service.timeline(self.team["underwriter"], record["id"])
        self.assertEqual(len(timeline), len(flow) + 1)
        self.assertEqual(timeline[-1]["action"], "settle")
