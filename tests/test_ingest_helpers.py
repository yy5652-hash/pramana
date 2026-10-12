"""Pure functions of the ingestion and citation path: no files, no models."""
import httpx

from pramana.cite import best_excerpt, citation, place
from pramana.ingest.pdf import _anchor, _block_markdown, _figure_box, _normalise, _paragraphs
from pramana.ingest.video import clock, passages
from pramana.llm import _retry_delay, parse_json, repair_latex, repair_maths


def test_normalise_keeps_a_map_back_to_the_original_text():
    text = "Thus,  we can\nuse  the symbol"
    normal, index_map = _normalise(text)
    assert normal == "thus, we can use the symbol"
    start = normal.find("use")
    assert text[index_map[start]: index_map[start] + 3] == "use"


def test_anchor_skips_maths_that_the_text_layer_does_not_have():
    pieces = ["The vector $\\vec{f}$ represents the friction acting on the car, and it acts to the left."]
    assert _anchor(pieces, from_end=False) == "represents the friction acting on"
    assert _anchor(pieces, from_end=True) == "it acts to the left."
    assert _anchor(["$$ a = F/m $$"], from_end=False) is None


def test_figure_box_prefers_embedded_image_bounds_over_the_model_estimate():
    image = [0.12, 0.07, 0.88, 0.59]
    assert _figure_box([60, 117, 597, 868], [image]) == image          # model box overlaps the image: snap to it
    assert _figure_box([700, 100, 900, 500], [image]) == [0.1, 0.7, 0.5, 0.9]   # no overlap: keep the estimate
    assert _figure_box([500, 100, 400, 500], [image]) is None           # inverted box
    assert _figure_box(None, [image]) is None


def test_equation_blocks_keep_their_number():
    assert _block_markdown({"type": "equation", "text": "x = x_0 + \\bar{v}t", "label": "3.10"}) == "$$ x = x_0 + \\bar{v}t $$ (3.10)"
    assert _block_markdown({"type": "heading", "text": "Free Fall"}) == "### Free Fall"


def test_text_layer_paragraphs_break_on_sentence_ends():
    lines = "\n".join(["word " * 12 + "end."] * 12)
    assert len(_paragraphs(lines)) >= 2


def test_passages_end_on_sentences_and_cover_every_word():
    words = []
    t = 0.0
    for sentence in range(30):
        for i in range(12):
            words.append({"w": f" w{sentence}_{i}" + ("." if i == 11 else ""), "s": t, "e": t + 0.3})
            t += 0.35
    out = passages(words)
    assert all(p["text"].endswith(".") for p in out)
    assert all(25 <= p["t_end"] - p["t_start"] <= 61 for p in out[:-1])
    assert sum(len(p["text"].split()) for p in out) == len(words)
    assert out[0]["t_start"] == 0.0 and abs(out[-1]["t_end"] - words[-1]["e"]) < 1e-9


def test_clock_and_place_labels():
    assert clock(133.4) == "2:13"
    assert place({"kind": "text", "locator": {"page": 216}}) == "p. 216"
    assert place({"kind": "figure", "locator": {"page": 215, "label": "Figure 5.10"}}) == "p. 215, Figure 5.10"
    assert place({"kind": "slide", "locator": {"slide": 13}}) == "slide 13"
    assert place({"kind": "transcript", "locator": {"t_start": 133.2, "t_end": 177.9}}) == "2:13"
    assert place({"kind": "frame", "locator": {"t_start": 133.2, "t_end": 177.9, "t_frame": 177.4}}) == "2:57"


def test_best_excerpt_picks_the_sentence_closest_to_the_claim():
    text = "Friction opposes motion. The SI unit of force is the newton, defined as one kilogram metre per second squared. Mass is not weight."
    assert best_excerpt(text, "What is the unit of force? The newton.").startswith("The SI unit of force is the newton")


def test_citation_links_to_the_exact_place():
    unit = {"id": "v:t133", "kind": "transcript", "modality": "speech", "section": "4.1", "asset": "v/f00133.jpg",
            "text": "Newton's first law.", "locator": {"t_start": 133.2, "t_end": 177.9}}
    source = {"id": "v", "title": "4.1 Newton's First and Second Laws", "kind": "video", "file": "l04.mp4", "licence": "CC BY-NC-SA 4.0"}
    c = citation("mechanics", unit, source)
    assert c["media"] == "/media/mechanics/l04.mp4" and c["place"] == "2:13" and c["page_image"] is None
    page = {"id": "b:p3:1", "kind": "text", "modality": "vision", "section": "s", "asset": "b/p0003.jpg", "text": "x", "locator": {"page": 3, "rect": [0, 0, 1, 1]}}
    assert citation("mechanics", page, {"id": "b", "title": "Book", "kind": "textbook", "file": "b.pdf"})["page_image"] == "/assets/mechanics/b/p0003.jpg"


def test_model_replies_are_parsed_despite_fences_and_prose():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Here you go: {"a": [1, 2]} hope it helps') == {"a": [1, 2]}


def test_a_daily_quota_parks_the_model_for_the_whole_delay():
    daily = httpx.Response(429, text='{"error": {"details": [{"retryDelay": "33343s"}]}}')
    minute = httpx.Response(429, text='{"error": {"details": [{"retryDelay": "17s"}]}}')
    assert _retry_delay(daily, 0) > 30000
    assert _retry_delay(minute, 0) == 18.0
    assert _retry_delay(httpx.Response(503, text="overloaded"), 2) == 20.0


def test_the_chain_is_a_preference_order_and_a_resting_model_is_skipped():
    from pramana.llm import _Limiter

    limiter = _Limiter(requests_per_minute=60)
    assert limiter.reserve(["a", "b"])[0] == "a"
    assert limiter.reserve(["a", "b"])[0] == "a"          # pacing alone never moves down the chain
    limiter.cool_down("a", 30)
    model, wait = limiter.reserve(["a", "b"])
    assert model == "b" and wait < 1.5
    limiter.cool_down("b", 40000)
    assert limiter.reserve(["a", "b"])[0] == "a"          # everything resting: take the one back soonest
    assert not limiter.exhausted(["a", "b"])
    limiter.cool_down("a", 40000)
    assert limiter.exhausted(["a", "b"])


def test_latex_mangled_by_json_escaping_is_restored():
    eaten = parse_json('{"stem": "Power is $P = \\frac{dW}{dt}$ and $\\theta = 30$, so $v \\neq 0$."}'.replace("\\\\", "\\"))
    assert "\x0c" in eaten["stem"] and "\t" in eaten["stem"]            # what the JSON parser made of it
    assert repair_latex(eaten)["stem"] == "Power is $P = \\frac{dW}{dt}$ and $\\theta = 30$, so $v \\neq 0$."
    doubled = {"stem": "Total: $\\\\Delta x = 4\\\\text{ m}$", "options": ["$\\\\vec{F}$"]}
    assert repair_latex(doubled) == {"stem": "Total: $\\Delta x = 4\\text{ m}$", "options": ["$\\vec{F}$"]}
    fine = "Line one.\nnot maths, e.g. a tab\there. $$ a \\\\ b $$"
    assert repair_latex(fine) == fine                                    # ordinary text and real line breaks are left alone


def test_an_equation_block_is_repaired_without_dollar_signs():
    # A page's equation blocks arrive as bare LaTeX; the vision reader wraps them in $$ afterwards.
    block = "P_{\text{ave}} = \x0crac{\triangle W}{\triangle t}"       # what the JSON parser made of \\text, \\frac and \\triangle
    assert repair_latex(block) != "P_{\\text{ave}} = \\frac{\\triangle W}{\\triangle t}"   # the general repair cannot know it is maths
    assert repair_maths(block) == "P_{\\text{ave}} = \\frac{\\triangle W}{\\triangle t}"
    assert repair_maths("a \\\\Delta b") == "a \\Delta b"


def test_an_excerpt_never_ends_inside_a_formula():
    from pramana.cite import _close_maths, plain_start

    assert _close_maths("speed is $$ |v(t)| = \\sqrt{") == "speed is…"
    assert _close_maths("where $a$ is constant and $v_0") == "where $a$ is constant and…"
    assert _close_maths("where $a$ is constant.") == "where $a$ is constant."
    long = "### Heading\n\n" + "word " * 70 + "$$ x = x_0 + v_0 t + \\frac{1}{2} a t^2 $$"
    assert plain_start(long).count("$") % 2 == 0 and plain_start(long).startswith("Heading. word")
