from utils.config import Config


def test_required_config_fields():
    assert Config.NAME
    assert Config.USER_NAME
    assert Config.WAKE_WORDS
    assert Config.MODES
    assert Config.SYSTEM_PROMPT_STANDARD


def test_apps_include_core_targets():
    for app in ["chrome", "vscode", "youtube", "github", "gmail"]:
        assert app in Config.APPS


def test_folder_shortcuts():
    for folder in ["desktop", "downloads", "documents"]:
        assert folder in Config.FOLDER_SHORTCUTS


def test_udp_ports_distinct():
    assert Config.UDP_PORT_UI != Config.UDP_PORT_ASSISTANT
    assert 0 < Config.UDP_PORT_UI < 65536
    assert 0 < Config.UDP_PORT_ASSISTANT < 65536
