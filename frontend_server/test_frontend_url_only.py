from pathlib import Path
import re


root = Path(__file__).resolve().parent
public = root / "public"
html = (public / "index.html").read_text(encoding="utf-8")
app = (public / "static" / "app.js").read_text(encoding="utf-8")


def opening_tag(element_id: str) -> str:
    match = re.search(rf"<(?:button|section)\b[^>]*\bid=\"{re.escape(element_id)}\"[^>]*>", html, re.S)
    assert match, f"missing element: {element_id}"
    return match.group(0)


assert 'href="/static/styles.css"' in html
assert 'src="/static/app.js"' in html
assert (public / "static" / "styles.css").is_file()
assert (public / "static" / "app.js").is_file()
assert " hidden" in opening_tag("directModeTab")
assert " hidden" in opening_tag("directInputPane")
assert " hidden" not in opening_tag("urlModeTab")
assert " hidden" not in opening_tag("urlInputPane")
assert 'let inputMode = "url";' in app
assert 'option value="verify" selected' in html
assert "공개 조선일보 기사" in html
print("frontend_url_only_static_contract=PASS")
