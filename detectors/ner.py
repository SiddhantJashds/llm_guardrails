"""NER-backed detectors for the identifiers regex can't catch: person names
(`full_name`) and place names (`geographic_subdivision` / `residential_address`).

Deterministic in the sense docs/adr/0004 cares about: a pinned local spaCy
model (see detectors/requirements.txt), no LLM call, same text -> same hits.
Still a statistical model, though, so its hits are treated as LOW confidence
downstream (detectors/scoring/signals.py) -- see docs/adr/0008.

Fail-closed: if the model can't be loaded, `find_names`/`find_locations`
raise `NERUnavailableError` rather than quietly returning [] (which would
look like "clean text"). Set GUARDRAILS_NER_DISABLED=1 to opt out explicitly
(regex-only mode) -- e.g. a dev laptop without the model downloaded.
"""
import logging
import os
import re
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

MODEL_NAME = "en_core_web_sm"

_NLP = None


class NERUnavailableError(RuntimeError):
    """The NER model is required but couldn't be loaded."""


def ner_disabled() -> bool:
    return os.environ.get("GUARDRAILS_NER_DISABLED") == "1"


def load_model():
    """Load (once) and return the spaCy pipeline; None if explicitly disabled."""
    global _NLP
    if ner_disabled():
        logger.warning("GUARDRAILS_NER_DISABLED=1: name/place detection is OFF (regex-only)")
        return None
    if _NLP is None:
        try:
            import spacy

            # Only the NER component is needed; the rest just costs latency.
            _NLP = spacy.load(MODEL_NAME, disable=["tagger", "parser", "attribute_ruler", "lemmatizer"])
        except Exception as exc:  # ImportError, OSError (model missing), ...
            raise NERUnavailableError(
                f"spaCy model '{MODEL_NAME}' unavailable ({exc}); run `pip install -r requirements-dev.txt` "
                "or set GUARDRAILS_NER_DISABLED=1 to run regex-only"
            ) from exc
    return _NLP


# ----------------------------------------------------------- false-positive filters

# HIPAA Safe Harbor only lists geographic units SMALLER than a state, so
# states/provinces and countries are NOT identifiers -- don't flag them.
_STATE_LEVEL_AND_ABOVE = frozenset(
    s.lower()
    for s in [
        # US states, DC, territories + abbreviations
        "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware",
        "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
        "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi",
        "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico",
        "New York", "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania",
        "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
        "Virginia", "Washington State", "West Virginia", "Wisconsin", "Wyoming", "District of Columbia",
        "Puerto Rico", "Guam",
        # Indian states / UTs (DPDP pack)
        "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
        "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
        "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan",
        "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
        "Andaman and Nicobar Islands", "Chandigarh", "Ladakh", "Lakshadweep", "Puducherry",
        "Jammu and Kashmir", "Delhi",
        # Countries / regions
        "United States", "United States of America", "US", "U.S.", "USA", "U.S.A.", "America",
        "United Kingdom", "UK", "U.K.", "England", "Scotland", "Wales", "Ireland", "Canada", "Mexico",
        "India", "China", "Japan", "Pakistan", "Bangladesh", "Sri Lanka", "Nepal", "Australia",
        "New Zealand", "Germany", "France", "Spain", "Italy", "Portugal", "Netherlands", "Belgium",
        "Switzerland", "Sweden", "Norway", "Denmark", "Finland", "Poland", "Russia", "Ukraine",
        "Turkey", "Israel", "Iran", "Iraq", "Saudi Arabia", "United Arab Emirates", "UAE", "Egypt",
        "South Africa", "Nigeria", "Kenya", "Brazil", "Argentina", "Chile", "Colombia", "Peru",
        "South Korea", "Korea", "Singapore", "Malaysia", "Indonesia", "Thailand", "Vietnam",
        "Philippines", "Europe", "Asia", "Africa", "North America", "South America", "Middle East",
    ]
)

# Eponymous diseases spaCy tags as PERSON. Applied ONLY when the whole entity is
# one of these single words ("Parkinson" alone) -- never to a multi-word name,
# so a patient called "Sarah Parkinson" is still caught. Deliberately excludes
# terms that are also common given names/surnames (Addison, Bell, Wilson,
# Turner, Graves, ...): a missed name is a PHI leak, a redacted disease name
# is only a utility hit. Multi-word / possessive forms are handled by
# _CONDITION_SUFFIX below instead.
_NON_PII_PERSON_TERMS = frozenset(
    {
        "parkinson", "alzheimer", "crohn", "down", "hodgkin", "huntington", "asperger", "tourette",
        "raynaud", "lyme", "apgar", "marfan", "hashimoto", "sjogren", "guillain", "kawasaki",
        "klinefelter", "ehlers", "danlos", "meniere", "reye", "babinski", "cheyne",
    }
)
# "<Name>'s disease", "<Name> syndrome", ... -> a condition, not a patient.
_CONDITION_SUFFIX = re.compile(
    r"^(?:['’]s)?\s+(?:disease|syndrome|palsy|lymphoma|sign|test|score|scale|criteria|"
    r"classification|reflex|law|maneuver|manoeuvre|procedure|anemia|anaemia|fracture|cycle)\b",
    re.IGNORECASE,
)

_PERSON_LABELS = {"PERSON"}
# FAC (facilities/landmarks) deliberately excluded: too noisy for too little gain.
_LOCATION_LABELS = {"GPE", "LOC"}


def _normalize(entity_text: str) -> str:
    t = entity_text.strip().lower()
    t = re.sub(r"^the\s+", "", t)
    return re.sub(r"['’]s$", "", t)


def _is_person(ent, text: str) -> bool:
    if not any(ch.isalpha() for ch in ent.text) or any(ch.isdigit() for ch in ent.text):
        return False
    if _CONDITION_SUFFIX.match(text[ent.end_char : ent.end_char + 40]):
        return False
    return _normalize(ent.text) not in _NON_PII_PERSON_TERMS


def _is_subdivision(ent) -> bool:
    if not any(ch.isalpha() for ch in ent.text) or any(ch.isdigit() for ch in ent.text):
        return False
    return _normalize(ent.text) not in _STATE_LEVEL_AND_ABOVE


def _entities(text: str, labels: set, keep) -> List[str]:
    nlp = load_model()
    if nlp is None or not text.strip():
        return []
    doc = nlp(text)
    seen: List[str] = []
    for ent in doc.ents:
        span = ent.text.strip()
        if ent.label_ in labels and span not in seen and keep(ent, text):
            seen.append(span)
    return seen


def find_names(text: str) -> List[Tuple[str, str]]:
    """[("full_name", span), ...] for PERSON entities, minus known clinical eponyms."""
    return [("full_name", s) for s in _entities(text, _PERSON_LABELS, lambda e, t: _is_person(e, t))]


def find_locations(text: str, identifier: str = "geographic_subdivision") -> List[Tuple[str, str]]:
    """[(identifier, span), ...] for city/county/etc. -- state-level and above are ignored
    (Safe Harbor only covers units smaller than a state)."""
    return [(identifier, s) for s in _entities(text, _LOCATION_LABELS, lambda e, _t: _is_subdivision(e))]
