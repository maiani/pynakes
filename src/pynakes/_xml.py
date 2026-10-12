"""Parsing XML that arrives from outside: provider responses and MODS imports."""

from xml.etree import ElementTree as ET


def parse_untrusted_xml(text: str) -> ET.Element:
    """Parse ``text``, refusing entity declarations.

    No format pynakes reads needs its own entities, and declaring them is how
    an expansion bomb is built. A plain DOCTYPE naming an external DTD (as NCBI
    responses carry) is accepted; the DTD itself is never fetched. Raises
    :class:`xml.etree.ElementTree.ParseError` for malformed or refused input.
    """
    if "<!ENTITY" in text:
        raise ET.ParseError("XML entity declarations are not accepted")
    return ET.fromstring(text)
