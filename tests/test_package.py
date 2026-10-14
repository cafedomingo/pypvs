"""The package's public names."""

import pypvs


def test_everything_in_all_is_importable():
    missing = [name for name in pypvs.__all__ if not hasattr(pypvs, name)]
    assert missing == []


def test_pvs_hass_can_import_its_errors_from_pypvs_pvs():
    import pypvs.pvs

    assert pypvs.pvs.PVSAuthenticationError is pypvs.PVSAuthenticationError
    assert pypvs.pvs.PVSCommunicationError is pypvs.PVSCommunicationError
