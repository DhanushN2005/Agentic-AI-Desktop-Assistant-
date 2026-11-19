"""The redesigned dashboard (interface/web_ui_v2.html) and its opt-in route on the bridge."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = (ROOT / "interface" / "web_ui_v2.html").read_text(encoding="utf-8")


def test_bridge_serves_the_new_dashboard_by_default_and_classic_on_request():
    import interface.web_ui_bridge as br
    assert pathlib.Path(br.HTML_FILE_V2).name == "web_ui_v2.html" and pathlib.Path(br.HTML_FILE).name == "web_ui.html"
    src = (ROOT / "interface" / "web_ui_bridge.py").read_text(encoding="utf-8")
    assert '"/v2": HTML_FILE_V2' in src and '"/classic": HTML_FILE' in src
    assert '"/": default' in src and 'FLEXIE_WEB_UI' in src and '== "classic"' in src      # "/" is the new dashboard unless FLEXIE_WEB_UI=classic


def test_v2_gets_the_per_run_token_injected():
    import interface.web_ui_bridge as br
    html = br._render_html(br.HTML_FILE_V2).decode("utf-8")
    assert br.AUTH_TOKEN in html and "{{AUTH_TOKEN}}" not in html


def test_v2_speaks_the_same_protocol_as_the_classic_dashboard():
    for tag in ("STATE", "SAY", "METRICS", "MODE", "JOB", "MCP", "STREAM", "NOTIFY", "ALARM", "REMINDER", "ERROR"):
        assert f"tag === '{tag}'" in PAGE, tag
    assert "'AUTH:' + AUTH_TOKEN" in PAGE and "AUTH_OK" in PAGE and "FlexiePanels.handle(tag, val)" in PAGE   # approvals still reach panels.js
    assert "GET_SETTINGS" in PAGE and "SAVE_SETTINGS:" in PAGE and "SETTINGS_SAVED" in PAGE      # the merged API keys / settings protocol


def test_v2_is_self_contained_and_never_injects_data_as_html():
    assert not re.search(r"\.innerHTML|insertAdjacentHTML|document\.write", PAGE)                     # chat, mail, queries use textContent
    assert not re.search(r"""(?:src|href)=["']https?://""", PAGE)                                      # no CDN assets
    assert "default-src 'none'" in PAGE and "object-src 'none'" in PAGE
    assert "Demo data" in PAGE and "demo=1" in PAGE                                                    # demo data is opt-in and labelled in the page


def test_dashboard_has_exactly_two_modules_home_and_settings():
    modules = re.findall(r'class="nav"[^>]*data-v="(\w+)"', PAGE)
    assert sorted(modules) == ["home", "settings"]
    assert 'id="v-home"' in PAGE and 'id="v-settings"' in PAGE and len(re.findall(r'<main class="view', PAGE)) == 2


def test_home_follows_the_design_spec_sections():
    for needle in ("System Health", "Performance Trends", "Recent Activity", "Active Services", "Storage Overview", "Quick Actions",
                   "Ask Flexie OS anything", "AI-Powered Business OS", "CPU Usage", "Memory Usage", "Disk Usage", "Network I/O"):
        assert needle in PAGE, needle
    assert 'aria-current="page"' in PAGE and "prefers-reduced-motion" in PAGE and 'aria-label="Notifications"' in PAGE


def test_settings_merge_keys_behavior_orb_styles_and_apply_live():
    for needle in ("AI providers", "Behavior", "Appearance", "Connection", "Applies instantly", "Applies after restart", "Save and apply", "orb_style",
                   "Floating orb on your desktop", "Orb on this page", "autocomplete: 'new-password'"):
        assert needle in PAGE, needle
    assert "pl.keys = draft.keys" in PAGE and "type: 'password'" in PAGE          # keys are typed into password fields and sent once


def test_canvases_cannot_grow_the_layout_and_long_text_is_clamped():
    assert "c._h = c.clientHeight" in PAGE and "c.style.height = c._h" in PAGE                 # pinned box: no feedback from the bitmap size
    assert 'id="sStore"' not in PAGE and 'id="sbarFill"' in PAGE                                 # the unsized storage canvas is gone
    assert "-webkit-line-clamp:2" in PAGE and "function clip(" in PAGE                           # replies and feed lines are shortened, click to read all
