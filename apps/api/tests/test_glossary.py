"""Glossary page parser (M2.2 seeding): the four layouts, aliases, skipped sections."""

from app.graph.glossary import clean_term, parse

WRAP = '<html><body><div class="mw-parser-output">{}</div></body></html>'


def test_glossary_template_and_plain_definition_lists():
    page = WRAP.format(
        '<h2>A</h2><dl class="glossary"><dt class="glossary"><dfn>abstract data type (ADT)</dfn>'
        '</dt><dd class="glossary">A data type defined by its behaviour. It hides details.'
        '<sup class="reference">[3]</sup></dd>'
        "<dt>agile</dt><dd>An iterative way of building software.</dd></dl>"
        "<dl><dt>Algorithm</dt><dd>A finite sequence of steps.</dd></dl>"
    )
    got = parse(page)
    assert [(e.label, e.aliases) for e in got] == [
        ("Abstract data type", ("ADT",)),
        ("Agile", ()),
        ("Algorithm", ()),
    ]
    assert got[0].snippet == "A data type defined by its behaviour."  # first sentence, no [3]


def test_bold_term_lists_need_a_separator():
    page = WRAP.format(
        "<ul><li><b>Abdomen</b> – The part of the body between the chest and pelvis.</li>"
        "<li><b>Aorta</b>: the main artery.</li>"
        "<li>See <b>Heart</b> for more</li>"  # text before the bold term: not an entry
        "<li><b>Portal</b> page</li></ul>"  # no separator: not an entry
    )
    assert [e.label for e in parse(page)] == ["Abdomen", "Aorta"]
    commented = WRAP.format("<ul><li><b>Bile</b><!-- note --> – A digestive fluid.</li></ul>")
    assert [e.label for e in parse(commented)] == ["Bile"]


def test_heading_per_term_layout_only_on_heading_heavy_pages():
    terms = "".join(f"<h3>Term {i}</h3><p>Definition {i}. More.</p>" for i in range(25))
    assert len(parse(WRAP.format(terms))) == 25
    few = "".join(f"<h3>Section {i}</h3><p>Text.</p>" for i in range(5))
    assert parse(WRAP.format(few)) == []  # ordinary section headings are not terms


def test_see_also_references_and_navboxes_are_skipped():
    page = WRAP.format(
        "<dl><dt>Bond</dt><dd>A debt security.</dd></dl>"
        "<h2>See also</h2><ul><li><b>Glossary of finance</b> – another page.</li></ul>"
        '<div class="navbox"><dl><dt>Navigation</dt><dd>Links.</dd></dl></div>'
    )
    assert [e.label for e in parse(page)] == ["Bond"]


def test_clean_term_rejects_non_terms_and_keeps_first_variant():
    assert clean_term("colour, color") == ("Colour", ())
    assert clean_term("leg before wicket (LBW)") == ("Leg before wicket", ("LBW",))
    assert clean_term("1") is None and clean_term("") is None
    assert clean_term("x" * 120) is None
