import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import build_service
from src.domain import Conflict, PermissionDenied
from tests.helpers import ORG_A, seed_admin, seed_team


LEGACY_PAYLOAD = {'event_id': 'CAT-2025-07', 'attachment': 1000000.0, 'limit': 5000000.0, 'cession_pct': 0.4, 'loss_amount': 3000000.0, 'reinstatement_pct': 0.15, 'aggregate_prior': 0.0, 'layer_width': 4000000.0, 'recoverable_amount': 800000.0, 'reinstatement_premium': 120000.0, 'net_retention': 2200000.0}

OLD_SCHEMA = """
CREATE TABLE records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    payload TEXT NOT NULL,
    created_by TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    details TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def make_legacy_db(path):
    connection = sqlite3.connect(str(path))
    connection.executescript(OLD_SCHEMA)
    connection.execute(
        "INSERT INTO records(reference,state,version,payload,created_by,updated_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        ("LEG-9001", "claim_submitted", 3, json.dumps(LEGACY_PAYLOAD), "legacy", "legacy", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
    )
    connection.commit()
    connection.close()


class LegacyAssignmentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db_path = Path(self.temp.name) / "legacy.db"
        make_legacy_db(db_path)
        self.service = build_service(str(db_path))
        self.team = seed_team(self.service)
        self.admin = seed_admin(self.service)
        self.legacy_id = 1

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_record_lands_in_pending_queue(self):
        pending = self.service.pending_assignments(self.admin)
        self.assertEqual([item["id"] for item in pending], [self.legacy_id])
        self.assertIsNone(pending[0]["org"])
        with self.assertRaises(PermissionDenied):
            self.service.pending_assignments(self.team["finance"])
        # 分公司列表与详情都看不到待分配赔案
        self.assertEqual(self.service.list_records(self.team["claims"]), [])
        with self.assertRaises(PermissionDenied):
            self.service.get_record(self.team["claims"], self.legacy_id)

    def test_unassigned_record_cannot_be_calculated_or_settled(self):
        with self.assertRaises(Conflict):
            self.service.act(self.admin, self.legacy_id, 3, "calculate", {"approved_loss": 2800000.0})
        with self.assertRaises(Conflict):
            self.service.act(self.admin, self.legacy_id, 3, "settle", {"payment_reference": "PAY-9"})

    def test_only_hq_admin_can_assign_org(self):
        with self.assertRaises(PermissionDenied):
            self.service.act(self.team["finance"], self.legacy_id, 3, "assign_org", {"org": ORG_A})
        with self.assertRaises(Conflict):
            self.service.act(self.admin, self.legacy_id, 1, "assign_org", {"org": ORG_A})
        record = self.service.act(self.admin, self.legacy_id, 3, "assign_org", {"org": ORG_A})
        self.assertEqual(record["org"], ORG_A)
        self.assertEqual(record["state"], "claim_submitted")
        with self.assertRaises(Conflict):
            self.service.act(self.admin, self.legacy_id, record["version"], "assign_org", {"org": ORG_A})
        # 补全后本分公司可以核定
        record = self.service.act(self.team["claims"], record["id"], record["version"], "calculate", {"approved_loss": 2800000.0})
        self.assertEqual(record["state"], "calculated")
