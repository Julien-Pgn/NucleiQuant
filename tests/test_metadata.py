import pytest

from nucleiquant import metadata


def test_v1_pattern_parses_shipped_names():
    f = metadata.parse_filename("Pa_dQ_J70_SNd2T_20Xa_g1dt08_OG1_s1.tif")
    assert f == {"clone": "Pa", "diff": "dQ", "day": "J70", "immuno": "SNd2T", "objective": "20Xa",
                 "imaging": "g1dt08", "organoid": "OG1", "slice": "s1"}
    assert metadata.parse_filename("Pa_dQ_J70_SNd2T_20Xa_g1dt08_OG1_s1_labels.tif")["slice"] == "s1"


def test_malformed_names_raise():
    with pytest.raises(ValueError):
        metadata.parse_filename("Pa_dQ_J70_OG1_s1.tif")
    with pytest.raises(ValueError):
        metadata.parse_filename("Pa_dQ_J70_SNd2T_20Xa_g1dt08_OG1_slice1.tif")


def test_template_default_is_v1_pattern():
    assert metadata.pattern_from_template(metadata.DEFAULT_TEMPLATE) is metadata.FILENAME_PATTERN


def test_custom_template():
    pat = metadata.pattern_from_template("clone_day_organoid_slice")
    assert metadata.parse_filename("KO3_D45_org2_s04.tiff", pat) == {"clone": "KO3", "day": "D45", "organoid": "org2", "slice": "s04"}
    with pytest.raises(ValueError):
        metadata.parse_filename("KO3_D45.tif", pat)


@pytest.mark.parametrize("bad", ["", "clone__slice", "clone_clone", "clone_sl-ice"])
def test_bad_templates(bad):
    with pytest.raises(ValueError):
        metadata.pattern_from_template(bad)
