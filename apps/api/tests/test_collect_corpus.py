from scripts.collect_corpus import (
    Item,
    Source,
    allocate,
    canonical,
    interleave,
    is_relevant,
    parse_feed,
    parse_wiki_page,
)

SRC = Source("bbc", ("https://feeds.example/rss.xml",), ("/news/articles/",))

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Business</title><link>https://www.bbc.co.uk/news/business</link>
<item><title>Rate cut hopes lift shares</title>
  <link>https://www.bbc.co.uk/news/articles/abc123?at_medium=RSS&amp;at_campaign=rss</link>
  <pubDate>Fri, 03 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>Watch: markets in 60 seconds</title>
  <link>https://www.bbc.co.uk/news/articles/vid999</link></item>
<item><title>Cup final report</title>
  <link>https://www.bbc.co.uk/sport/football/1</link></item>
<item><title>No link here</title></item>
</channel></rss>"""


def item(feed: int, ts: float, url: str) -> Item:
    return Item("s", feed, ts, url, "t")


def test_canonical_drops_query_fragment_and_normalizes_host():
    assert (
        canonical("HTTPS://WWW.BBC.CO.UK/news/articles/abc?at_medium=RSS#top")
        == "https://www.bbc.co.uk/news/articles/abc"
    )


def test_relevance_needs_section_prefix_and_rejects_formats_and_titles():
    assert is_relevant(SRC, "https://x/news/articles/1", "Repo rate held")
    assert not is_relevant(SRC, "https://x/sport/1", "Repo rate held")
    guardian = Source("guardian", (), ("/business/",))
    assert not is_relevant(guardian, "https://x/business/live/2026/oct/03/x", "Markets")
    assert not is_relevant(guardian, "https://x/business/2026/x", "Stocks to buy today")
    assert not is_relevant(guardian, "https://x/business/2026/x", "  ")
    et = Source("et", (), ("/markets/",))
    assert not is_relevant(et, "https://x/markets/stocks/recos/buy-x/1.cms", "Buy X")
    assert not is_relevant(et, "https://x/markets/prime/1.cms", "Deep dive")


def test_parse_feed_keeps_only_relevant_items_with_canonical_urls():
    items = parse_feed(SRC, 0, RSS)
    assert [i.url for i in items] == ["https://www.bbc.co.uk/news/articles/abc123"]
    assert items[0].title == "Rate cut hopes lift shares"
    assert items[0].published > 0


def test_interleave_round_robins_feeds_newest_first_and_dedupes():
    items = [
        item(0, 1, "a-old"),
        item(0, 5, "a-new"),
        item(1, 3, "b1"),
        item(1, 2, "a-new"),  # same story in a second feed
        item(1, 1, "b3"),
    ]
    assert [i.url for i in interleave(items)] == ["a-new", "b1", "a-old", "b3"]


def test_allocate_even_split_with_shortfall_redistributed():
    assert allocate({"a": 100, "b": 100, "c": 100}, 30) == {"a": 10, "b": 10, "c": 10}
    assert allocate({"a": 5, "b": 100, "c": 100}, 31) == {"a": 5, "b": 13, "c": 13}
    assert allocate({"a": 3, "b": 4}, 30) == {"a": 3, "b": 4}
    assert allocate({"a": 0, "b": 10}, 4) == {"a": 0, "b": 4}
    assert allocate({}, 10) == {}


def test_parse_wiki_page_reads_canonical_title_and_qid():
    html = (
        '<link rel="canonical" href="https://en.wikipedia.org/wiki/Repurchase_agreement">'
        '<script>RLCONF={"wgCategories":["Finance"],"wgWikibaseItemId":"Q169357"}</script>'
    )
    page = parse_wiki_page(html)
    assert page is not None
    assert page.url == "https://en.wikipedia.org/wiki/Repurchase_agreement"
    assert page.title == "Repurchase agreement"
    assert page.qid == "Q169357"


def test_parse_wiki_page_rejects_disambiguation():
    html = (
        '<link rel="canonical" href="https://en.wikipedia.org/wiki/Yield">'
        '"wgCategories":["Disambiguation pages","All article disambiguation pages"]'
    )
    assert parse_wiki_page(html) is None
