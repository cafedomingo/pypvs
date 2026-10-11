"""pypvs.api against SunStrong's published variable lists."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from pypvs.api import (
    INTERFACES_BY_MODEL,
    PVS6_ONLY_VARIABLES,
    Model,
    Variable,
    net_state,
)

DOC = Path(__file__).parent.parent / "doc"


def documented(model: Model) -> set[str]:
    path = DOC / f"varserver-variables-public-{model.lower()}.csv"
    with path.open() as f:
        return {row["name"] for row in csv.DictReader(f)}


def test_every_variable_is_documented_for_the_pvs6():
    assert set(Variable) <= documented(Model.PVS6)


def test_pvs6_only_variables_are_the_ones_the_pvs5_lacks():
    assert set(Variable) - documented(Model.PVS5) == PVS6_ONLY_VARIABLES


@pytest.mark.parametrize("model", list(Model))
def test_interfaces_are_the_documented_ones(model):
    states = {n for n in documented(model) if n.startswith("/net/")}
    assert {net_state(i) for i in INTERFACES_BY_MODEL[model]} == states


def test_members_print_like_plain_strings():
    assert repr(Variable.MODEL) == repr("/sys/info/model")
    assert str({Variable.MODEL: 1}) == str({"/sys/info/model": 1})
