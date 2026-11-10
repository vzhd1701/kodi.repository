import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "update_addons.py"
SPEC = importlib.util.spec_from_file_location("update_addons", MODULE)
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self.source = self.root / "source"
        self.source.mkdir()
        self.addon_id = "plugin.video.example"
        self.addon = self.source / self.addon_id
        self.addon.mkdir()
        self.spec = {
            "id": self.addon_id,
            "repository": "example/addon",
            "branch": "master",
            "path": self.addon_id,
        }
        self.write_config([self.spec])
        catalog = (
            '<addons><addon id="plugin.video.example" version="0.0.3" />'
            '<addon id="repository.example" version="2.0.0">'
            '<extension point="xbmc.addon.repository" /></addon></addons>\n'
        ).encode()
        (self.repository / "addons.xml").write_bytes(catalog)
        self.write_checksum()
        subprocess.run(["git", "init", "--quiet", str(self.source)], check=True)
        self.write_source("0.0.4")
        (self.addon / "addon.py").write_text("print('example')\n")
        subprocess.run(
            ["git", "-C", str(self.source), "add", "--", self.addon_id], check=True
        )
        # This private, untracked file must never enter a published ZIP.
        (self.addon / "local-password.txt").write_text("do not package")

    def write_source(self, version, addon_id=None):
        (self.addon / "addon.xml").write_text(
            '<addon id="' + (addon_id or self.addon_id) + '" version="' + version + '">'
            '<extension point="xbmc.addon.metadata"><news>Login fix</news></extension></addon>'
        )

    def write_checksum(self):
        content = (self.repository / "addons.xml").read_bytes()
        (self.repository / "addons.xml.sha256").write_text(
            hashlib.sha256(content).hexdigest()
        )

    def write_config(self, sources):
        (self.repository / "addon-sources.json").write_text(json.dumps(sources))

    def run_update(self):
        return publisher.update_repository(
            self.repository, {self.addon_id: self.source}
        )

    def test_new_version_publishes_package_metadata_and_matching_checksum(self):
        self.assertEqual(self.run_update(), [self.addon_id + " 0.0.4"])
        catalog_bytes = (self.repository / "addons.xml").read_bytes()
        catalog = ET.fromstring(catalog_bytes)
        self.assertEqual(catalog[0].attrib["version"], "0.0.4")
        self.assertEqual(catalog[0].find("extension/news").text, "Login fix")
        self.assertEqual(catalog[1].attrib["id"], "repository.example")
        self.assertEqual(catalog[1].attrib["version"], "2.0.0")
        self.assertEqual(
            (self.repository / "addons.xml.sha256").read_text(),
            hashlib.sha256(catalog_bytes).hexdigest(),
        )
        with ZipFile(
            self.repository / self.addon_id / (self.addon_id + "-0.0.4.zip")
        ) as bundle:
            self.assertEqual(
                set(bundle.namelist()),
                {self.addon_id + "/addon.xml", self.addon_id + "/addon.py"},
            )
            self.assertEqual(
                ET.fromstring(bundle.read(self.addon_id + "/addon.xml")).attrib[
                    "version"
                ],
                "0.0.4",
            )

    def test_repeated_run_leaves_all_published_bytes_unchanged(self):
        self.run_update()
        before = {
            path: path.read_bytes()
            for path in self.repository.rglob("*")
            if path.is_file()
        }
        self.assertEqual(self.run_update(), [])
        self.assertEqual(
            before,
            {
                path: path.read_bytes()
                for path in self.repository.rglob("*")
                if path.is_file()
            },
        )

    def test_older_source_does_not_downgrade_catalog(self):
        self.write_source("0.0.2")
        before = (self.repository / "addons.xml").read_bytes()
        self.assertEqual(self.run_update(), [])
        self.assertEqual((self.repository / "addons.xml").read_bytes(), before)
        self.assertFalse((self.repository / self.addon_id).exists())

    def test_bad_checksum_stops_before_writing(self):
        (self.repository / "addons.xml.sha256").write_text("invalid")
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.run_update()
        self.assertFalse((self.repository / self.addon_id).exists())

    def test_mismatched_addon_id_is_rejected(self):
        self.write_source("0.0.4", "plugin.video.wrong")
        with self.assertRaisesRegex(ValueError, "ID does not match"):
            self.run_update()
        self.assertFalse((self.repository / self.addon_id).exists())

    def test_later_failure_does_not_partially_publish_first_addon(self):
        other = dict(self.spec, id="plugin.video.missing")
        self.write_config([self.spec, other])
        before = (self.repository / "addons.xml").read_bytes()
        with self.assertRaisesRegex(ValueError, "ID does not match"):
            publisher.update_repository(
                self.repository, {self.addon_id: self.source, other["id"]: self.source}
            )
        self.assertEqual((self.repository / "addons.xml").read_bytes(), before)
        self.assertFalse((self.repository / self.addon_id).exists())

    def test_new_addon_can_be_added_to_catalog(self):
        (self.repository / "addons.xml").write_bytes(
            b'<addons><addon id="repository.example" version="2.0.0" /></addons>'
        )
        self.write_checksum()
        self.assertEqual(self.run_update(), [self.addon_id + " 0.0.4"])
        self.assertEqual(len(ET.parse(self.repository / "addons.xml").getroot()), 2)

    def test_duplicate_config_ids_are_rejected(self):
        self.write_config([self.spec, self.spec])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.run_update()

    def test_source_path_cannot_escape_checkout(self):
        self.write_config([dict(self.spec, path="../outside")])
        with self.assertRaisesRegex(ValueError, "inside"):
            self.run_update()

    def test_published_archive_is_never_overwritten(self):
        folder = self.repository / self.addon_id
        folder.mkdir()
        archive = folder / (self.addon_id + "-0.0.4.zip")
        archive.write_bytes(b"existing release")
        with self.assertRaisesRegex(ValueError, "overwrite"):
            self.run_update()
        self.assertEqual(archive.read_bytes(), b"existing release")

    def test_numeric_version_comparison(self):
        self.assertGreater(
            publisher.version_key("0.0.10"), publisher.version_key("0.0.9")
        )
        self.assertEqual(publisher.version_key("1.0"), publisher.version_key("1.0.0"))
        self.assertGreater(publisher.version_key("1.0.1"), publisher.version_key("1.0"))
        with self.assertRaisesRegex(ValueError, "stable numeric"):
            publisher.version_key("1.0.0-beta1")


if __name__ == "__main__":
    unittest.main()
