"""Tests for validator.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest
from config_models import PowerSeqConfig, PowerRail
from validator import (
    check_duplicate_names,
    check_missing_deps,
    check_circular_dependency,
    validate,
)


class TestCheckDuplicateNames:
    def test_no_duplicates(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A"),
            PowerRail("B"),
        ])
        assert check_duplicate_names(cfg) == []

    def test_has_duplicates(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A"),
            PowerRail("B"),
            PowerRail("A"),
        ])
        assert check_duplicate_names(cfg) == ["A"]


class TestCheckMissingDeps:
    def test_all_exist(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["__HIGH__"]),
            PowerRail("B", depends_on_hi=["A"]),
        ])
        assert check_missing_deps(cfg) == []

    def test_missing_dep(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["NOT_EXIST"]),
        ])
        assert check_missing_deps(cfg) == [("A", "NOT_EXIST")]

    def test_high_low_constants_ignored(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["__HIGH__"], depends_on_lo=["__LOW__"]),
        ])
        assert check_missing_deps(cfg) == []


class TestCheckCircularDependency:
    def test_no_cycle(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["__HIGH__"]),
            PowerRail("B", depends_on_hi=["A"]),
        ])
        assert check_circular_dependency(cfg) is False

    def test_cycle_in_hi(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["B"]),
            PowerRail("B", depends_on_hi=["A"]),
        ])
        assert check_circular_dependency(cfg) is True

    def test_cycle_in_lo(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["__HIGH__"], depends_on_lo=["B"]),
            PowerRail("B", depends_on_hi=["__HIGH__"], depends_on_lo=["A"]),
        ])
        assert check_circular_dependency(cfg) is True

    def test_hi_lo_cross_no_cycle(self):
        """SIG_3 iHi 依賴 SIG_2、SIG_2 iLo 依賴 SIG_3 不形成環"""
        cfg = PowerSeqConfig(rails=[
            PowerRail("SIG_2", depends_on_hi=["__HIGH__"], depends_on_lo=["SIG_3"]),
            PowerRail("SIG_3", depends_on_hi=["SIG_2"], depends_on_lo=["__LOW__"]),
        ])
        assert check_circular_dependency(cfg) is False


class TestValidate:
    def test_valid_config(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["__HIGH__"]),
            PowerRail("B", depends_on_hi=["A"]),
        ])
        ok, errs = validate(cfg)
        assert ok is True
        assert errs == []

    def test_duplicate_fails(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A"),
            PowerRail("A"),
        ])
        ok, errs = validate(cfg)
        assert ok is False
        assert any("Duplicate" in e for e in errs)

    def test_missing_dep_fails(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["MISSING"]),
        ])
        ok, errs = validate(cfg)
        assert ok is False
        assert any("non-existent" in e for e in errs)

    def test_circular_fails(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["B"]),
            PowerRail("B", depends_on_hi=["A"]),
        ])
        ok, errs = validate(cfg)
        assert ok is False
        assert any("Circular" in e for e in errs)

    def test_empty_name_fails(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("", depends_on_hi=["__HIGH__"]),
        ])
        ok, errs = validate(cfg)
        assert ok is False
        assert any("empty" in e for e in errs)
