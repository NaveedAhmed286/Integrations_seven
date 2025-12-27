import os
import sys
import json
import types
import importlib
import pytest

# Helper: create a very small dummy Sheets service used by the agent during tests
def _make_dummy_sheets_service():
    class DummyService:
        def __init__(self):
            self._last_rows = []
        def spreadsheets(self):
            return self
        def values(self):
            return self
        def append(self, spreadsheetId=None, range=None, valueInputOption=None, insertDataOption=None, body=None):
            self._last_rows = body.get("values", [])
            return self
        def get(self, spreadsheetId=None):
            # used by test_connection in agent
            return self
        def execute(self):
            # return a structure similar to Google API
            return {"updates": {"updatedRows": len(self._last_rows)}}
    return DummyService()

@pytest.fixture
def amazon_agent(monkeypatch):
    """
    Prepare environment and import app.agent after patching external libraries.
    Returns a fresh AmazonAgent instance.
    """

    # 1) Minimal env vars needed by AmazonAgent.__init__
    fake_sa = {
        "type": "service_account",
        "project_id": "dummy-project",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIID...FAKE\n-----END PRIVATE KEY-----\n",
        "client_email": "test@dummy.iam.gserviceaccount.com"
    }
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", json.dumps(fake_sa))
    monkeypatch.setenv("SPREADSHEET_ID", "sheet_test_123")
    monkeypatch.setenv("SHEET_NAME", "Sheet1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")  # tests use fallback or patched deepseek

    # 2) Ensure googleapiclient and oauth modules exist (create lightweight fakes if not installed)
    if "googleapiclient" not in sys.modules:
        ga = types.ModuleType("googleapiclient")
        ga.discovery = types.SimpleNamespace()
        sys.modules["googleapiclient"] = ga
        sys.modules["googleapiclient.discovery"] = ga.discovery
    if "google.oauth2" not in sys.modules:
        go = types.ModuleType("google.oauth2")
        go.service_account = types.SimpleNamespace()
        sys.modules["google.oauth2"] = go
        sys.modules["google.oauth2.service_account"] = go.service_account

    # 3) Patch build() to return a dummy Sheets service and Credentials.from_service_account_info to dummy
    try:
        import googleapiclient.discovery as gad
        monkeypatch.setattr(gad, "build", lambda service, version, credentials=None: _make_dummy_sheets_service(), raising=False)
    except Exception:
        # already created fake module above; assign build there
        sys.modules["googleapiclient"].discovery.build = lambda service, version, credentials=None: _make_dummy_sheets_service()

    try:
        import google.oauth2.service_account as gas
        monkeypatch.setattr(gas.Credentials, "from_service_account_info", lambda info, scopes=None: object(), raising=False)
    except Exception:
        # put the callable into fake module
        sys.modules["google.oauth2.service_account"].Credentials = types.SimpleNamespace(from_service_account_info=lambda info, scopes=None: object())

    # 4) Patch app.apify_client & app.memory_manager used by agent (lightweight async stubs)
    # We'll create simple dummy objects that mimic the async call signatures
    class DummyApifyClient:
        async def quick_test(self):
            return True
        async def scrape_amazon_products(self, **kwargs):
            # default: return no products — tests will patch when needed
            return {"success": True, "products": []}

    class DummyMemoryManager:
        async def learn_from_analysis(self, *args, **kwargs):
            return True

    # Ensure the app package is importable
    import importlib as _importlib
    try:
        _importlib.import_module("app")
    except Exception:
        # if package import fails, raise so tests surface it
        pass

    monkeypatch.setattr("app.apify_client", DummyApifyClient(), raising=False)
    monkeypatch.setattr("app.memory_manager", DummyMemoryManager(), raising=False)

    # 5) Import (or reload) app.agent now that environment & fakes are in place
    agent_mod = importlib.import_module("app.agent")
    importlib.reload(agent_mod)

    # 6) Create a fresh AmazonAgent instance
    inst = agent_mod.AmazonAgent()
    return inst
