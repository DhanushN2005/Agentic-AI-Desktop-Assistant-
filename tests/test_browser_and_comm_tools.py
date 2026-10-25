"""Unit and integration tests for Browser & Email Communication Tools."""
from unittest.mock import MagicMock
import pytest

from core.tool_registry import ToolRegistry, PermissionLevel
from core.browser_and_comm_tools import register_browser_and_comm_tools
from core.handlers.system import handle_comm


class TestBrowserAndCommTools:
    def test_registration(self):
        reg = ToolRegistry()
        mock_orch = MagicMock()
        count = register_browser_and_comm_tools(reg, mock_orch)
        assert count == 8

        names = reg.list_tool_names()
        expected = [
            "browser_navigate", "browser_search", "browser_click",
            "browser_fill", "browser_extract", "email_read_unread",
            "email_reply", "email_send"
        ]
        for name in expected:
            assert name in names

    def test_browser_tools_execution(self):
        reg = ToolRegistry()
        mock_orch = MagicMock()
        mock_orch.browser.navigate.return_value = "Navigated to https://example.com"
        mock_orch.browser.search_in_browser.return_value = "Searched for 'python' in Chrome."
        mock_orch.browser.click_element.return_value = "Clicked button"
        mock_orch.browser.fill_field.return_value = "Filled username"
        mock_orch.browser.extract_page_data.return_value = "Extracted page text"

        register_browser_and_comm_tools(reg, mock_orch)

        # 1. Navigate
        r1 = reg.execute("browser_navigate", {"url": "https://example.com"})
        assert r1.success is True
        assert "Navigated to" in r1.message
        mock_orch.browser.navigate.assert_called_once_with("https://example.com")

        # 2. Search
        r2 = reg.execute("browser_search", {"query": "python"})
        assert r2.success is True
        assert "Searched for" in r2.message
        mock_orch.browser.search_in_browser.assert_called_once_with("python")

        # 3. Click
        r3 = reg.execute("browser_click", {"selector_or_text": "Login"})
        assert r3.success is True
        mock_orch.browser.click_element.assert_called_once_with("Login")

        # 4. Fill
        r4 = reg.execute("browser_fill", {"selector_or_label": "Username", "value": "testuser"})
        assert r4.success is True
        mock_orch.browser.fill_field.assert_called_once_with("Username", "testuser")

        # 5. Extract
        r5 = reg.execute("browser_extract", {"mode": "text"})
        assert r5.success is True
        mock_orch.browser.extract_page_data.assert_called_once_with(mode="text")

    def test_email_tools_execution(self):
        reg = ToolRegistry()
        mock_orch = MagicMock()
        mock_orch.email.get_unread_emails_detailed.return_value = [
            {"from": "alice@example.com", "subject": "Project Update", "preview": "Hello, here is update."}
        ]
        mock_orch.email.reply_email.return_value = "Successfully sent reply to alice@example.com."
        mock_orch.email.send_email.return_value = "Successfully sent email to bob@example.com."

        register_browser_and_comm_tools(reg, mock_orch)

        # 1. Read unread
        r_read = reg.execute("email_read_unread", {"count": 2})
        assert r_read.success is True
        assert "alice@example.com" in r_read.message

        # 2. Reply email
        r_reply = reg.execute("email_reply", {
            "to": "alice@example.com",
            "body": "Got the update, thanks!",
            "subject": "Project Update",
        })
        assert r_reply.success is True
        assert "Successfully sent reply" in r_reply.message
        mock_orch.email.reply_email.assert_called_once_with(
            to="alice@example.com",
            body="Got the update, thanks!",
            subject="Project Update",
        )

        # 3. Send email
        r_send = reg.execute("email_send", {
            "to": "bob@example.com",
            "subject": "Meeting",
            "body": "Let's meet tomorrow.",
        })
        assert r_send.success is True
        mock_orch.email.send_email.assert_called_once_with(
            to="bob@example.com",
            subject="Meeting",
            body="Let's meet tomorrow.",
        )

    def test_handle_comm_reply_to_email_flow(self):
        mock_orch = MagicMock()
        mock_orch.email.get_unread_emails_detailed.return_value = [
            {"from": "mentor@example.com", "subject": "Review"}
        ]
        mock_orch.email.reply_email.return_value = "Successfully sent email to mentor@example.com."
        mock_orch.speak = MagicMock()

        res = handle_comm(mock_orch, "reply to email saying sounds good see you then")
        assert res is True
        mock_orch.email.reply_email.assert_called_once_with(
            "mentor@example.com",
            "sounds good see you then",
            subject="Review",
        )
        mock_orch.speak.assert_called_with("Successfully sent email to mentor@example.com.")
