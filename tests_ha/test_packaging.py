"""Tests that the integration's files are consistent with each other."""

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "custom_components" / "neevo_tank"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_bundled_library_matches_source() -> None:
    """HACS only installs the integration folder, so the library is copied in."""
    source = ROOT / "src" / "pyneevo"
    files = sorted(path.relative_to(source) for path in source.rglob("*.py"))
    assert files
    for relative in files:
        bundled = INTEGRATION / "pyneevo" / relative
        assert bundled.read_text(encoding="utf-8").split() == (
            source / relative
        ).read_text(encoding="utf-8").split(), f"{relative} is out of date"


def test_manifest() -> None:
    manifest = load(INTEGRATION / "manifest.json")
    assert manifest["domain"] == INTEGRATION.name
    for key in ("name", "version", "documentation", "issue_tracker", "codeowners"):
        assert manifest[key]
    # Home Assistant requires domain and name first, then alphabetical order.
    keys = list(manifest)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_hacs_files() -> None:
    assert load(ROOT / "hacs.json")["name"]
    assert (INTEGRATION / "brand" / "icon.png").read_bytes().startswith(b"\x89PNG")


def test_every_entity_has_a_name_and_icon() -> None:
    sensor_source = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    keys = set(re.findall(r'translation_key="(\w+)"', sensor_source))
    assert keys
    names = load(INTEGRATION / "translations" / "en.json")["entity"]
    icons = load(INTEGRATION / "icons.json")["entity"]
    assert keys == set(names["sensor"])
    assert keys == set(icons["sensor"])
    assert "reading_overdue" in names["binary_sensor"]
    assert "reading_overdue" in icons["binary_sensor"]


def test_no_change_operations_are_bundled() -> None:
    """The integration only reads from the Nee-Vo service."""
    source = "".join(
        path.read_text(encoding="utf-8") for path in INTEGRATION.rglob("*.py")
    )
    for name in (
        "DeletePropaneDevice",
        "DeleteUser",
        "RevokePropaneDeviceAuthorization",
        "GenerateAccessAutorizationVoucher",
        "GenerateTransfertAutorizationVoucher",
        "UpdateCampaignClickCount",
        "UpdatePropaneDevice",
        "UpdateUser",
        "ChangePassword",
        "SendFillRequest",
        "RegisterPropaneDevice",
    ):
        assert f'"{name}' not in source
