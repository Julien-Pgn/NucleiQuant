"""Filename metadata parser for the NucleiQuant pipeline.

Filenames follow the convention:
    clone_diff_day_immuno_objective_imaging_organoid_slice...

parse_filename() extracts these fields and raises ValueError if a filename
doesn't match the convention. Other conventions can be described with a
template such as "clone_day_organoid_slice" (see pattern_from_template).
"""

import re

__all__ = [
    "FILENAME_PATTERN", "FIELDS", "DEFAULT_TEMPLATE",
    "parse_filename", "pattern_from_template", "template_fields",
]

FILENAME_PATTERN = re.compile(
    r"^(?P<clone>[^_]+)_(?P<diff>[^_]+)_(?P<day>[^_]+)_(?P<immuno>[^_]+)"
    r"_(?P<objective>[^_]+)_(?P<imaging>[^_]+)_(?P<organoid>[^_]+)"
    r"_(?P<slice>s\d+)(?:[_.].*)?$"
)

FIELDS = ("clone", "diff", "day", "immuno", "objective", "imaging", "organoid", "slice")

DEFAULT_TEMPLATE = "_".join(FIELDS)

_FIELD_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")


def template_fields(template):
    """Field names of an underscore-separated template, validated."""
    fields = [f.strip() for f in template.strip().split("_")]
    if not fields or any(not _FIELD_NAME.match(f) for f in fields):
        raise ValueError(
            "The pattern must be field names separated by '_' (letters and digits only), "
            f"e.g. {DEFAULT_TEMPLATE!r}"
        )
    if len(set(fields)) != len(fields):
        raise ValueError("Each field name can only appear once in the pattern")
    return fields


def pattern_from_template(template):
    """Compile a regex from a template like 'clone_day_organoid_slice'.

    The V1 template returns the exact V1 pattern (slice must look like s1, s2...).
    """
    fields = template_fields(template)
    if fields == list(FIELDS):
        return FILENAME_PATTERN
    parts = [f"(?P<{f}>[^_.]+)" for f in fields]
    return re.compile("^" + "_".join(parts) + r"(?:[_.].*)?$")


def parse_filename(filename, pattern=FILENAME_PATTERN):
    """Parse one filename into its metadata fields.

    Returns a dict with one key per named group of `pattern`. Raises
    ValueError if filename doesn't match the expected naming convention.
    """
    match = pattern.match(filename)
    if match is None:
        raise ValueError(f"Filename does not match the expected naming convention: {filename!r}")
    return match.groupdict()
