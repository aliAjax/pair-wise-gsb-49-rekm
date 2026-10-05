import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import build_service
from src.domain import HQ_ORG, Actor, Conflict, PermissionDenied


EAST = "east"
WEST = "west"
HQ_ADMIN = Actor("hq-admin", "admin", HQ_ORG)
CREATE_DATA = {'event_id': 'CAT-2026-01', 'attachment': 1000000.0, 'limit': 5000000.0, 'cession_pct': 0.4, 'loss_amount': 3000000.0, 'reinstatement_pct': 0.15, 'aggregate_prior': 0.0}
BIG_DATA = {'event_id': 'CAT-2026-99', 'attachment': 1000000.0, 'limit': 20000000.0, 'cession_pct': 0.5, 'loss_amount': 20000000.0, 'reinstatement_pct': 0.1, 'aggregate_prior': 0.0}


class TenancyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = build_service(str(Path(self.temp.name) / "test.db"))

    def tearDown(self):
        self.temp.cleanup()

    def _create_east(self, reference="RI-1", data=None):
        return self.service.create(Actor("uw-east", "underwriter", EAST), reference, data or CREATE_DATA)

    def _push_to_calculated(self, record, org=EAST, approved_loss=20000000.0, calculated_by="claims-east"):
        record = self.service.act(Actor("uw-2", "underwriter", org), record["id"], record["version"], "bind", {"underwriter_id": "UW-8"})
        record = self.service.act(Actor("claims-1", "claims_officer", org), record["id"], record["version"], "submit_claim", {"claim_number": "CLM-1", "event_id": record["payload"]["event_id"]})
        return self.service.act(Actor(calculated_by, "claims_officer", org), record["id"], record["version"], "calculate", {"approved_loss": approved_loss})

    def test_create_pins_org_to_identity(self):
        record = self._create_east(data=dict(CREATE_DATA, org=WEST))
        self.assertEqual(record["org"], EAST)
        self.assertNotIn("org", record["payload"])

    def test_create_requires_branch_identity(self):
        with self.assertRaises(PermissionDenied):
            self.service.create(Actor("no-org", "underwriter"), "RI-X", CREATE_DATA)
        with self.assertRaises(PermissionDenied):
            self.service.create(HQ_ADMIN, "RI-Y", CREATE_DATA)

    def test_cross_branch_read_and_write_denied(self):
        record = self._create_east()
        west_clerk = Actor("claims-west", "claims_officer", WEST)
        with self.assertRaises(PermissionDenied):
            self.service.get_record(west_clerk, record["id"])
        with self.assertRaises(PermissionDenied):
            self.service.timeline(west_clerk, record["id"])
        with self.assertRaises(PermissionDenied):
            self.service.act(Actor("uw-west", "underwriter", WEST), record["id"], record["version"], "bind", {"underwriter_id": "UW-9"})
        self.assertEqual(self.service.list_records(west_clerk), [])
        self.assertEqual(self.service.stats(west_clerk), {})
        self.assertEqual(self.service.get_record(HQ_ADMIN, record["id"])["org"], EAST)
        self.assertEqual(len(self.service.list_records(HQ_ADMIN)), 1)
        self.assertEqual(self.service.stats(HQ_ADMIN), {"quoted": 1})

    def test_pending_queue_and_assignment(self):
        prepared = self.service.rules.prepare_create(CREATE_DATA)
        legacy = self.service.repository.create("LEG-1", "claim_submitted", prepared, "legacy", "")
        branch_clerk = Actor("claims-east", "claims_officer", EAST)
        with self.assertRaises(PermissionDenied):
            self.service.get_record(branch_clerk, legacy["id"])
        with self.assertRaises(PermissionDenied):
            self.service.pending_assignments(branch_clerk)
        with self.assertRaises(PermissionDenied):
            self.service.assign_org(branch_clerk, legacy["id"], EAST, legacy["version"])
        pending = self.service.pending_assignments(HQ_ADMIN)
        self.assertEqual([item["id"] for item in pending], [legacy["id"]])
        with self.assertRaises(Conflict):
            self.service.act(HQ_ADMIN, legacy["id"], legacy["version"], "calculate", {"approved_loss": 1000000.0})
        with self.assertRaises(Conflict):
            self.service.assign_org(HQ_ADMIN, legacy["id"], EAST, legacy["version"] + 9)
        assigned = self.service.assign_org(HQ_ADMIN, legacy["id"], EAST, legacy["version"])
        self.assertEqual(assigned["org"], EAST)
        self.assertEqual(self.service.pending_assignments(HQ_ADMIN), [])
        with self.assertRaises(Conflict):
            self.service.assign_org(HQ_ADMIN, legacy["id"], WEST, assigned["version"])
        record = self.service.act(Actor("claims-east", "claims_officer", EAST), assigned["id"], assigned["version"], "calculate", {"approved_loss": 1000000.0})
        self.assertEqual(record["state"], "calculated")

    def test_unassigned_cannot_settle(self):
        prepared = self.service.rules.prepare_create(CREATE_DATA)
        prepared["recoverable_amount"] = 100.0
        legacy = self.service.repository.create("LEG-2", "calculated", prepared, "legacy", "")
        with self.assertRaises(Conflict):
            self.service.act(HQ_ADMIN, legacy["id"], legacy["version"], "settle", {"payment_reference": "PAY-1"})

    def test_large_claim_requires_second_finance_review(self):
        record = self._push_to_calculated(self._create_east("RI-BIG", BIG_DATA))
        self.assertGreater(record["payload"]["recoverable_amount"], 5000000.0)
        with self.assertRaises(Conflict):
            self.service.act(Actor("fin-east-a", "finance", EAST), record["id"], record["version"], "settle", {"payment_reference": "PAY-1"})
        with self.assertRaises(PermissionDenied):
            self.service.act(Actor("claims-east", "finance", EAST), record["id"], record["version"], "review", {})
        reviewed = self.service.act(Actor("fin-east-b", "finance", EAST), record["id"], record["version"], "review", {"comment": "复核通过"})
        self.assertEqual(reviewed["state"], "calculated")
        self.assertEqual(reviewed["payload"]["reviewed_by"], "fin-east-b")
        settled = self.service.act(Actor("fin-east-a", "finance", EAST), reviewed["id"], reviewed["version"], "settle", {"payment_reference": "PAY-1"})
        self.assertEqual(settled["state"], "settled")

    def test_concurrent_submission_first_wins(self):
        record = self._push_to_calculated(self._create_east("RI-RACE", BIG_DATA))
        version = record["version"]
        self.service.act(Actor("fin-east-a", "finance", EAST), record["id"], version, "review", {})
        with self.assertRaises(Conflict):
            self.service.act(Actor("fin-east-b", "finance", EAST), record["id"], version, "review", {})

    def test_legacy_rows_backfilled_to_pending_queue(self):
        db_path = Path(self.temp.name) / "legacy.db"
        connection = sqlite3.connect(str(db_path))
        connection.executescript(
            """
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
        )
        connection.execute(
            "INSERT INTO records(reference,state,version,payload,created_by,updated_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("LEG-0", "quoted", 1, json.dumps({"event_id": "CAT-OLD"}), "legacy", "legacy", "2026-01-01", "2026-01-01"),
        )
        connection.commit()
        connection.close()
        service = build_service(str(db_path))
        pending = service.pending_assignments(HQ_ADMIN)
        self.assertEqual([item["reference"] for item in pending], ["LEG-0"])
        self.assertEqual(pending[0]["org"], "")
