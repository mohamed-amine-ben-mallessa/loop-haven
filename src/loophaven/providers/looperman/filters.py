"""Looperman's own filter vocabulary, reversed from the internal AJAX endpoint.

Source of truth: ``POST /ajax/ajax_adv_search_modal`` with
``item_type=loops|acapellas`` and ``query_filter_params=base64("[]")``.
That endpoint returns the HTML of the advanced-search form actually served to
the user, so the ids below are the ones Looperman itself submits — not guesses
derived from slugs or from counting result pages.

Two consequences worth remembering:

* ``did`` (DAW) appears in the tag links of every card but is **not** a filter
  in the form, and sending it changes nothing. It is exposed as a read-only
  item field, never as a query filter.
* Listings cap the reported total at 5,000 ("Loops 1 - 25 of 5,000"), so a
  total of 5,000 means "5,000 or more".
"""

import difflib
import re

# --------------------------------------------------------------------------
# Vocabularies (id -> label), in the order Looperman serves them
# --------------------------------------------------------------------------

GENRES = {
    "56": "8Bit Chiptune", "52": "Acid", "3": "Acoustic", "67": "Afrobeat",
    "2": "Ambient", "66": "Big Room", "33": "Blues", "65": "Boom Bap",
    "37": "Breakbeat", "21": "Chill Out", "36": "Cinematic", "13": "Classical",
    "51": "Comedy", "44": "Country", "39": "Crunk", "17": "Dance",
    "55": "Dancehall", "30": "Deep House", "23": "Dirty", "18": "Disco",
    "11": "Drum And Bass", "5": "Dub", "49": "Dubstep", "64": "EDM",
    "42": "Electro", "16": "Electronic", "15": "Ethnic", "25": "Folk",
    "19": "Funk", "46": "Fusion", "24": "Garage", "31": "Glitch",
    "43": "Grime", "53": "Grunge", "48": "Hardcore", "61": "Hardstyle",
    "27": "Heavy Metal", "7": "Hip Hop", "22": "House", "63": "Indie",
    "38": "Industrial", "6": "Jazz", "10": "Jungle", "69": "Latin",
    "62": "Lo-Fi", "72": "Math Rock", "57": "Moombahton", "34": "Orchestral",
    "70": "Phonk", "50": "Pop", "60": "Psychedelic", "14": "Punk",
    "8": "Rap", "4": "Reggae", "32": "Reggaeton", "45": "Religious",
    "12": "RnB", "1": "Rock", "29": "Samba", "41": "Ska", "59": "Soul",
    "47": "Spoken Word", "9": "Techno", "28": "Trance", "54": "Trap",
    "58": "Trip Hop", "68": "UK Drill", "71": "Vaporwave", "35": "Weird",
}

CATEGORIES = {
    "40": "Accordion", "47": "Arpeggio", "35": "Bagpipe", "36": "Banjo",
    "2": "Bass", "43": "Bass Guitar", "44": "Bass Synth", "39": "Bass Wobble",
    "31": "Beatbox", "42": "Bells", "23": "Brass", "34": "Choir",
    "37": "Clarinet", "28": "Didgeridoo", "1": "Drum", "7": "Flute",
    "5": "Fx", "24": "Groove", "33": "Guitar Acoustic", "3": "Guitar Electric",
    "25": "Harmonica", "41": "Harp", "30": "Harpsichord", "32": "Mandolin",
    "22": "Orchestral", "26": "Organ", "11": "Pad", "20": "Percussion",
    "21": "Piano", "46": "Rhodes Piano", "12": "Scratch", "9": "Sitar",
    "45": "Soundscapes", "10": "Strings", "4": "Synth", "8": "Tabla",
    "38": "Ukulele", "29": "Violin", "6": "Vocal", "27": "Woodwind",
}

# Looperman only knows sharps: "s" = sharp, trailing "m" = minor.
KEYS = {
    "a": "A", "am": "Am", "as": "A#", "asm": "A#m",
    "b": "B", "bm": "Bm",
    "c": "C", "cm": "Cm", "cs": "C#", "csm": "C#m",
    "d": "D", "dm": "Dm", "ds": "D#", "dsm": "D#m",
    "e": "E", "em": "Em",
    "f": "F", "fm": "Fm", "fs": "F#", "fsm": "F#m",
    "g": "G", "gm": "Gm", "gs": "G#", "gsm": "G#m",
}

# Enharmonic aliases, because musicians write Bb, not A#.
KEY_FLAT_ALIASES = {
    "bb": "a", "bbm": "am", "db": "cs", "dbm": "csm", "eb": "ds", "ebm": "dsm",
    "gb": "fs", "gbm": "fsm", "ab": "gs", "abm": "gsm",
}

TIME_SIGNATURES = {"4x4": "4/4", "2x4": "2/4", "3x4": "3/4", "6x8": "6/8"}

WHEN = {
    "1": "Last 24 Hours", "5": "Last 48 Hours", "2": "Last 7 Days",
    "3": "Last 30 Days", "4": "Last 60 Days",
}

ORDERS = {
    "date": "Date", "name": "Title", "author": "Author", "genre": "Genre",
    "tempo": "Tempo", "fsize": "File Size", "duration": "Duration",
    "downloads": "Downloads", "favs": "Favourites", "comments": "Comments",
}

DIRECTIONS = {"d": "Descending", "a": "Ascending"}

PER_PAGE = {"25": 25, "50": 50, "100": 100}

WHO = {"1": "Followed Only", "2": "Remove Ignored"}

# Acapella-only vocabularies
USAGE_RIGHTS = {
    "1": "Free Commercial & Non Commercial",
    "2": "Free Non Commercial Only / Commercial Licence Required",
}
VOCAL_TYPES = {"1": "Hook", "2": "Verse", "3": "Full Song"}
VOCAL_GENDERS = {"1": "Male Vocal Only", "2": "Female Vocal Only", "3": "Both Male & Female"}
VOCAL_STYLES = {"1": "Rap Only", "2": "Singing Only", "3": "Rap & Singing"}
AUTOTUNE = {"1": "Didn't Use Autotune", "2": "Used Autotune"}
ADULT = {"y": "Has Adult Content", "n": "Remove Adult Content"}

# Listing pages stop counting at this value.
TOTAL_CAP = 5000


class UnknownFilter(ValueError):
    """A filter value Looperman does not know; carries close matches."""

    def __init__(self, name, value, suggestions):
        self.name = name
        self.value = value
        self.suggestions = suggestions
        hint = f" Suggestions: {', '.join(suggestions)}." if suggestions else ""
        super().__init__(f"{name}: unknown value {value!r}.{hint}")


def _norm(value):
    """'Boom Bap Loops' / 'boom-bap' / 'boom_bap' -> 'boom bap'."""
    text = str(value).strip().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9#]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _index(table, extra_suffixes=()):
    """Normalised label (and bare id) -> id."""
    index = {}
    for key_id, label in table.items():
        index.setdefault(_norm(label), key_id)
        index.setdefault(_norm(key_id), key_id)
        for suffix in extra_suffixes:
            index.setdefault(f"{_norm(label)} {suffix}", key_id)
    return index


_GENRE_INDEX = _index(GENRES, ("loops", "acapellas", "loop", "samples"))
_CATEGORY_INDEX = _index(CATEGORIES, ("loops", "loop", "samples"))


def _resolve(name, value, table, index, suffixes=()):
    """Accept an id, a label, or a slug and return (id, canonical label)."""
    if value is None or str(value).strip() == "":
        return None, None
    raw = str(value).strip()
    if raw in table:
        return raw, table[raw]
    normalised = _norm(raw)
    # "free-guitar-electric-loops-samples-sounds-wavs-download" and friends
    normalised = re.sub(r"^free ", "", normalised)
    if "loops samples" in normalised or "acapellas vocals" in normalised:
        normalised = re.sub(r" (loops?|acapellas?) samples.*$", "", normalised)
    for suffix in suffixes:
        if normalised.endswith(" " + suffix):
            normalised = normalised[: -len(suffix) - 1]
    if normalised in index:
        return index[normalised], table[index[normalised]]
    if normalised.endswith("s") and normalised[:-1] in index:
        return index[normalised[:-1]], table[index[normalised[:-1]]]
    choices = list(dict.fromkeys(_norm(label) for label in table.values()))
    suggestions = difflib.get_close_matches(normalised, choices, n=3, cutoff=0.5)
    if not suggestions:
        suggestions = choices[:5]
    raise UnknownFilter(name, value, [label.title() for label in suggestions])


def resolve_genre(value):
    return _resolve("genre", value, GENRES, _GENRE_INDEX, ("loops", "acapellas"))


def resolve_category(value):
    return _resolve("category", value, CATEGORIES, _CATEGORY_INDEX, ("loops",))


def resolve_key(value):
    """'Am', 'A#m', 'Bbm', 'F# minor' -> the mkey value Looperman expects."""
    if value is None or str(value).strip() == "":
        return None, None
    raw = str(value).strip()
    if raw.lower() in KEYS:
        return raw.lower(), KEYS[raw.lower()]
    text = _norm(raw).replace(" ", "")
    text = text.replace("minor", "m").replace("major", "")
    text = text.replace("#", "s").replace("♯", "s")
    text = text.replace("sharp", "s").replace("flat", "b")
    if text.endswith("min"):
        text = text[:-3] + "m"
    if text in KEYS:
        return text, KEYS[text]
    if text in KEY_FLAT_ALIASES:
        resolved = KEY_FLAT_ALIASES[text]
        return resolved, KEYS[resolved]
    raise UnknownFilter("key", value, [f"{label} ({key})" for key, label in list(KEYS.items())[:6]])


def resolve_choice(name, value, table, cast=str):
    """Resolve a small enum (when / who / type / style / ...)."""
    if value is None or str(value).strip() == "":
        return None, None
    raw = cast(value)
    key = str(raw).strip().lower()
    if key in table:
        return key, table[key]
    for known, label in table.items():
        if _norm(label) == _norm(key):
            return known, label
    raise UnknownFilter(name, value, [f"{k} ({v})" for k, v in table.items()])


def resolve_time_signature(value):
    if value is None or str(value).strip() == "":
        return None, None
    raw = str(value).strip().lower().replace(" ", "").replace("/", "x").replace(":", "x")
    if raw in TIME_SIGNATURES:
        return raw, TIME_SIGNATURES[raw]
    flat = re.sub(r"[^0-9x]", "", raw)
    if flat in TIME_SIGNATURES:
        return flat, TIME_SIGNATURES[flat]
    raise UnknownFilter("tsig", value, list(TIME_SIGNATURES))


def catalogue():
    """Everything a caller needs to build a valid query, machine-readable."""
    return {
        "genres": [{"id": k, "label": v} for k, v in GENRES.items()],
        "categories": [{"id": k, "label": v} for k, v in CATEGORIES.items()],
        "keys": [{"id": k, "label": v} for k, v in KEYS.items()],
        "time_signatures": [{"id": k, "label": v} for k, v in TIME_SIGNATURES.items()],
        "when": [{"id": k, "label": v} for k, v in WHEN.items()],
        "order": [{"id": k, "label": v} for k, v in ORDERS.items()],
        "dir": [{"id": k, "label": v} for k, v in DIRECTIONS.items()],
        "per_page": [int(k) for k in PER_PAGE],
        "who": [{"id": k, "label": v} for k, v in WHO.items()],
        "acapella": {
            "usage_rights": [{"id": k, "label": v} for k, v in USAGE_RIGHTS.items()],
            "vocal_type": [{"id": k, "label": v} for k, v in VOCAL_TYPES.items()],
            "vocal_gender": [{"id": k, "label": v} for k, v in VOCAL_GENDERS.items()],
            "vocal_style": [{"id": k, "label": v} for k, v in VOCAL_STYLES.items()],
            "autotune": [{"id": k, "label": v} for k, v in AUTOTUNE.items()],
            "adult": [{"id": k, "label": v} for k, v in ADULT.items()],
        },
        "notes": {
            "total_cap": TOTAL_CAP,
            "did": "DAW is a card field only: it is not a Looperman filter and is ignored upstream.",
            "loops": ["genre (gid)", "category (cid)", "key (mkey)", "bpm", "tsig", "when", "order", "dir", "keyword", "mid", "who", "ppage"],
            "acapellas": ["genre (gid)", "key (mkey)", "bpm", "tsig", "when", "order", "dir", "keyword", "mid", "who", "ppage", "rights", "genders", "style", "type", "autotune", "adult"],
        },
    }
