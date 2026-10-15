"""Packaging contract: the frozen exe must find the files Excel export needs.

Two separate failure modes are covered:
  - `core.paths` must resolve data dirs under `sys._MEIPASS` once frozen.
  - `build.py` must actually put those files into the bundle.

The second one also guards a confidentiality constraint: `templates/` holds
gitignored customer files, so the build may only pick named files out of it.
"""
import importlib
import os
import sys

import core.paths
from tools.build import build_command

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _reload_paths_as_frozen(monkeypatch, meipass):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    return importlib.reload(core.paths)


class TestFrozenPaths:
    def test_data_dirs_live_under_meipass_when_frozen(self, monkeypatch, tmp_path):
        paths = _reload_paths_as_frozen(monkeypatch, tmp_path)
        try:
            assert paths.TEMPLATES_DIR == tmp_path / "templates"
            assert paths.reference_dir() == tmp_path / "reference"
        finally:
            importlib.reload(core.paths)

    def test_data_dirs_follow_project_root_when_not_frozen(self):
        paths = importlib.reload(core.paths)
        assert paths.TEMPLATES_DIR == paths.PROJECT_ROOT / "templates"
        assert paths.reference_dir() == paths.SRC_DIR / "reference"

    def test_excel_export_template_candidates_follow_frozen_layout(self, monkeypatch, tmp_path):
        """excel_export caches template paths at import, so it must reload with paths."""
        pytest_openpyxl = importlib.util.find_spec("openpyxl")
        if pytest_openpyxl is None:
            import pytest

            pytest.skip("openpyxl missing")
        _reload_paths_as_frozen(monkeypatch, tmp_path)
        try:
            import excel.excel_export as excel_export

            excel_export = importlib.reload(excel_export)
            assert all(
                str(c).startswith(str(tmp_path)) for c in excel_export._TEMPLATE_CANDIDATES
            )
            assert str(excel_export.VBA_BIN).startswith(str(tmp_path))
        finally:
            importlib.reload(core.paths)
            import excel.excel_export as excel_export

            importlib.reload(excel_export)


class TestBuildBundlesExcelAssets:
    def _add_data(self, onefile=True):
        cmd = build_command(onefile=onefile)
        return [cmd[i + 1] for i, a in enumerate(cmd) if a == "--add-data"]

    def test_excel_template_is_bundled(self):
        targets = [spec.split(os.pathsep)[0] for spec in self._add_data()]
        assert any(t.endswith("powerseq_nodes_template.xlsm") for t in targets), targets

    def test_vba_project_is_bundled(self):
        specs = self._add_data()
        vba = [s for s in specs if s.split(os.pathsep)[0].endswith("vbaProject.bin")]
        assert vba, specs
        assert vba[0].split(os.pathsep)[1].replace("\\", "/") == "templates/vba"

    def test_templates_dir_is_never_bundled_wholesale(self):
        """templates/ contains gitignored customer workbooks — named files only."""
        templates_dir = os.path.normpath(os.path.join(PROJECT_ROOT, "templates"))
        for spec in self._add_data():
            source = os.path.normpath(spec.split(os.pathsep)[0])
            if not source.startswith(templates_dir):
                continue
            assert source != templates_dir, spec
            assert os.path.isfile(source), f"not a single file: {source}"

    def test_vba_helpers_need_no_scripts_path_workaround(self):
        """They live in src/excel/vba/, so normal import analysis collects them."""
        import excel.vba.embed_excel_vba  # noqa: F401
        import excel.vba.inject_vba_zip  # noqa: F401

        cmd = build_command(onefile=True)
        paths_args = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--paths"]
        assert not any(p.endswith("scripts") for p in paths_args), paths_args
        hidden = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--hidden-import"]
        assert "embed_excel_vba" not in hidden
        assert "inject_vba_zip" not in hidden
