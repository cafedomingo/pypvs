"""NamedVarReader: one rule per test, matching its docstring."""

from __future__ import annotations

import asyncio
import logging

import pytest

from pypvs.exceptions import PVSCommunicationError, PVSDataFormatError
from pypvs.updaters.named_reader import (
    BATCH_FAILURES_BEFORE_GIVING_UP,
    UNSUPPORTED_RETRY_S,
    NamedVarReader,
)

VALUES = {"/a": "1", "/b": "2", "/c": "3"}
BAD_REQUEST = PVSCommunicationError("HTTP 400", status=400)
SERVER_ERROR = PVSCommunicationError("HTTP 500", status=500)
UNREACHABLE = PVSCommunicationError("Cannot reach the PVS")


class FakePVS:
    """Like the real PVS: a name list with any unknown name is rejected with
    400 as a whole; `batch_error` / `single_errors` inject other failures."""

    def __init__(self, values, batch_error=None, single_errors=None, drop=()):
        self.values = dict(values)
        self.batch_error = batch_error
        self.single_errors = dict(single_errors or {})
        self.drop = set(drop)  # names a 200 batch leaves out
        self.batches: list[list[str]] = []
        self.singles: list[str] = []

    async def request_named_vars(self, names):
        self.batches.append(list(names))
        if self.batch_error:
            raise self.batch_error
        if any(n not in self.values for n in names):
            raise BAD_REQUEST
        return {n: self.values[n] for n in names if n not in self.drop}

    async def request_var(self, name):
        self.singles.append(name)
        if name in self.single_errors:
            raise self.single_errors[name]
        if name not in self.values:
            raise BAD_REQUEST
        return self.values[name]

    def reader(self, optional=("/c",)):
        return NamedVarReader(
            "test", self.request_var, self.request_named_vars, optional
        )


def read(reader, names=("/a", "/b", "/c"), now=0.0):
    return asyncio.run(reader.read(names, now))


def test_known_names_take_one_request():
    pvs = FakePVS(VALUES)
    values, errors = read(pvs.reader())
    assert values == VALUES and errors == {}
    assert pvs.batches == [["/a", "/b", "/c"]] and pvs.singles == []


def test_a_rejected_batch_falls_back_and_marks_an_unknown_optional_name():
    pvs = FakePVS({"/a": "1", "/b": "2"})  # no /c
    reader = pvs.reader()
    values, errors = read(reader)
    assert values == {"/a": "1", "/b": "2"}
    assert errors["/c"].status == 400
    assert pvs.singles == ["/a", "/b", "/c"]
    assert reader.is_unsupported("/c", 0.0)


def test_an_unknown_required_name_is_an_error_not_left_out():
    pvs = FakePVS({"/a": "1", "/c": "3"})  # no /b, which is required
    reader = pvs.reader()
    _, errors = read(reader)
    assert errors["/b"].status == 400
    assert not reader.is_unsupported("/b", 0.0)
    pvs.batches.clear()
    read(reader, now=30.0)
    assert "/b" in pvs.batches[0]  # still asked for


@pytest.mark.parametrize("error", [SERVER_ERROR, PVSDataFormatError("bad")])
def test_a_server_error_or_malformed_batch_falls_back(error):
    pvs = FakePVS(VALUES, batch_error=error)
    values, _ = read(pvs.reader())
    assert values == VALUES
    assert pvs.singles == ["/a", "/b", "/c"]


def test_a_partial_batch_reads_only_the_gaps():
    pvs = FakePVS(VALUES, drop={"/b"})
    values, _ = read(pvs.reader())
    assert values == VALUES
    assert pvs.singles == ["/b"]


def test_an_unsupported_name_is_left_out_then_retried_alone():
    pvs = FakePVS({"/a": "1", "/b": "2"})
    reader = pvs.reader()
    read(reader)
    pvs.batches.clear()
    pvs.singles.clear()
    values, errors = read(reader, now=30.0)
    assert pvs.batches == [["/a", "/b"]] and pvs.singles == []
    assert "/c" not in values and "/c" not in errors
    pvs.values["/c"] = "3"  # e.g. a battery commissioned later
    pvs.batches.clear()
    values, _ = read(reader, now=UNSUPPORTED_RETRY_S)
    assert values["/c"] == "3"
    assert pvs.batches == [["/a", "/b"]] and pvs.singles == ["/c"]
    assert not reader.is_unsupported("/c", UNSUPPORTED_RETRY_S)


def test_batching_gives_up_logs_once_and_retries_hourly(caplog):
    caplog.set_level(logging.INFO, logger="pypvs")
    pvs = FakePVS(VALUES, batch_error=SERVER_ERROR)
    reader = pvs.reader()
    for i in range(BATCH_FAILURES_BEFORE_GIVING_UP + 2):
        assert read(reader, now=i)[0] == VALUES
    assert len(pvs.batches) == BATCH_FAILURES_BEFORE_GIVING_UP
    read(reader, now=UNSUPPORTED_RETRY_S + 10)  # one batch again, still failing
    read(reader, now=UNSUPPORTED_RETRY_S + 20)  # and off again right away
    assert len(pvs.batches) == BATCH_FAILURES_BEFORE_GIVING_UP + 1
    assert caplog.text.count("keep failing") == 1
    pvs.batch_error = None  # fixed (e.g. firmware update)
    read(reader, now=2 * UNSUPPORTED_RETRY_S + 30)
    pvs.singles.clear()
    read(reader, now=2 * UNSUPPORTED_RETRY_S + 60)
    assert pvs.singles == []  # batching back on


@pytest.mark.parametrize("where", ["batch", "single"])
def test_an_unreachable_pvs_raises(where):
    pvs = FakePVS(
        VALUES,
        batch_error=UNREACHABLE if where == "batch" else SERVER_ERROR,
        single_errors={"/a": UNREACHABLE} if where == "single" else None,
    )
    with pytest.raises(PVSCommunicationError, match="Cannot reach"):
        read(pvs.reader())


def test_per_name_failures_are_returned_not_raised():
    empty = PVSDataFormatError("no value")
    pvs = FakePVS(
        VALUES,
        batch_error=SERVER_ERROR,
        single_errors={"/a": SERVER_ERROR, "/b": empty},
    )
    values, errors = read(pvs.reader())
    assert values == {"/c": "3"}
    assert errors == {"/a": SERVER_ERROR, "/b": empty}


def test_without_a_batch_reader_names_are_read_one_by_one():
    pvs = FakePVS(VALUES)
    reader = NamedVarReader("test", pvs.request_var, None)
    assert read(reader)[0] == VALUES
    assert pvs.batches == [] and pvs.singles == ["/a", "/b", "/c"]
