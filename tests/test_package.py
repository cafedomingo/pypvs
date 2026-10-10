"""The package's public names."""

import pypvs


def test_everything_in_all_is_importable():
    missing = [name for name in pypvs.__all__ if not hasattr(pypvs, name)]
    assert missing == []


def test_websocket_needs_a_host():
    import pytest

    from pypvs.pvs import PVS

    with pytest.raises(ValueError, match="host"):
        PVS(session=None).get_websocket()


def test_pvsdata_gateway_starts_empty():
    from pypvs.models.pvs import PVSData

    assert PVSData().gateway is None
