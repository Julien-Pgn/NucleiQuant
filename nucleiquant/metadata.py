"""Filename metadata parser for the NucleiQuant pipeline.

Filenames follow the convention:
    clone_diff_day_immuno_objective_imaging_organoid_slice...

parse_filename() extracts these fields and raises ValueError if a filename
doesn't match the convention.
"""

import re

__all__ = ["FILENAME_PATTERN", "FIELDS", "parse_filename"]

FILENAME_PATTERN = re.compile(
    r"^(?P<clone>[^_]+)_(?P<diff>[^_]+)_(?P<day>[^_]+)_(?P<immuno>[^_]+)"
    r"_(?P<objective>[^_]+)_(?P<imaging>[^_]+)_(?P<organoid>[^_]+)"
    r"_(?P<slice>s\d+)(?:[_.].*)?$"
)

FIELDS = ("clone", "diff", "day", "immuno", "objective", "imaging", "organoid", "slice")


def parse_filename(filename):
    """Parse one filename into its 8 metadata fields.

    Returns a dict with keys FIELDS. Raises ValueError if filename doesn't
    match the expected naming convention.
    """
    match = FILENAME_PATTERN.match(filename)
    if match is None:
        raise ValueError(f"Filename does not match the expected naming convention: {filename!r}")
    return match.groupdict()
