from pathlib import Path

CONTROL = "https://control.hope-johnstone.com"


def test_base_header_links_family_mark_to_5m_control():
    html = Path("app/templates/base.html").read_text()
    assert 'class="family-control"' in html
    assert f'href="{CONTROL}"' in html
    assert "5 Million Minutes" in html
    assert "control.bloodydaves.com" not in html
