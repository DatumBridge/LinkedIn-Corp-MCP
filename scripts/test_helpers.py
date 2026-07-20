#!/usr/bin/env python3
"""Unit tests for LinkedIn Corp MCP helpers (no live LinkedIn API)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.exceptions import LinkedInError, LinkedInValidationError
from app.services import linkedin_corp_service as lcs
from app.services.linkedin_corp_service import (
    LinkedInCorpService,
    build_org_ugc_text_body,
    encode_urn,
    load_credentials_dict,
    normalize_visibility,
    organization_urn_from_id,
    validate_organization_urn,
    validate_post_urn,
)


class TestOrganizationHelpers(unittest.TestCase):
    def test_organization_urn(self):
        self.assertEqual(
            organization_urn_from_id("12345"),
            "urn:li:organization:12345",
        )
        self.assertEqual(
            validate_organization_urn("urn:li:organization:99"),
            "urn:li:organization:99",
        )

    def test_organization_urn_rejects_person(self):
        with self.assertRaises(LinkedInValidationError):
            organization_urn_from_id("urn:li:person:1")
        with self.assertRaises(LinkedInValidationError):
            validate_organization_urn("urn:li:person:1")

    def test_visibility_defaults_public(self):
        self.assertEqual(normalize_visibility(None), "PUBLIC")

    def test_build_org_body(self):
        body = build_org_ugc_text_body(
            "urn:li:organization:42",
            "hello corp",
            visibility="PUBLIC",
        )
        self.assertEqual(body["author"], "urn:li:organization:42")


class TestCredentials(unittest.TestCase):
    def test_missing_credentials(self):
        with self.assertRaises(LinkedInError) as ctx:
            load_credentials_dict()
        self.assertEqual(ctx.exception.error_code, "CREDENTIALS_REQUIRED")

    def test_oauth_json(self):
        payload = {
            "type": "oauth",
            "access_token": "AQV.example",
            "scopes": ["w_organization_social"],
        }
        creds = load_credentials_dict(credentials_json=json.dumps(payload))
        self.assertEqual(creds["access_token"], payload["access_token"])


class TestAdminBinding(unittest.TestCase):
    def setUp(self):
        lcs._admin_org_cache.clear()
        lcs._create_events.clear()

    @patch.object(LinkedInCorpService, "_ensure_access_token", return_value="token")
    @patch.object(LinkedInCorpService, "list_my_organizations")
    def test_resolve_author_rejects_unknown_org(self, mock_list, _mock_token):
        mock_list.return_value = [
            {"organization_urn": "urn:li:organization:1"},
        ]
        service = LinkedInCorpService(
            credentials_json=json.dumps({"type": "oauth", "access_token": "x"})
        )
        with self.assertRaises(LinkedInValidationError):
            service.create_text_post(
                "urn:li:organization:999",
                "hi",
                dry_run=True,
            )

    @patch.object(LinkedInCorpService, "_ensure_access_token", return_value="token")
    @patch.object(LinkedInCorpService, "list_my_organizations")
    def test_resolve_author_accepts_admin_org(self, mock_list, _mock_token):
        mock_list.return_value = [
            {"organization_urn": "urn:li:organization:1"},
        ]
        service = LinkedInCorpService(
            credentials_json=json.dumps({"type": "oauth", "access_token": "x"})
        )
        result = service.create_text_post(
            "urn:li:organization:1",
            "hi",
            dry_run=True,
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["organization_urn"], "urn:li:organization:1")


class TestPostUrn(unittest.TestCase):
    def test_post_urn(self):
        self.assertEqual(validate_post_urn("urn:li:share:1"), "urn:li:share:1")
        encoded = encode_urn("urn:li:ugcPost:123")
        self.assertIn("%3A", encoded)


if __name__ == "__main__":
    unittest.main()
