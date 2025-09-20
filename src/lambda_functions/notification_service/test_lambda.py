import pytest
import json
import os
import boto3
from unittest.mock import patch, MagicMock
from moto import mock_aws
from lambda_function import (
    validate_environment_variables,
    validate_event_payload,
    format_notification_message,
    sanitize_event_summary,
    send_sms_notification,
    process_notification,
    lambda_handler,
)


class TestValidation:
    """Test validation functions"""

    def test_validate_environment_variables_success(self):
        """Test successful environment variable validation"""
        with patch.dict(
            os.environ,
            {
                "SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:calendar-notifications",
                "NOTIFICATION_MINUTES_BEFORE": "30",
            },
        ):
            topic_arn, minutes, errors = validate_environment_variables()
            assert (
                topic_arn == "arn:aws:sns:us-east-1:123456789012:calendar-notifications"
            )
            assert minutes == 30
            assert errors == []

    def test_validate_environment_variables_default_minutes(self):
        """Test default notification minutes when not specified"""
        with patch.dict(
            os.environ,
            {
                "SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:calendar-notifications"
            },
            clear=True,
        ):
            topic_arn, minutes, errors = validate_environment_variables()
            assert minutes == 15  # default value

    def test_validate_environment_variables_missing_sns(self):
        """Test missing SNS topic ARN"""
        with patch.dict(os.environ, {}, clear=True):
            topic_arn, minutes, errors = validate_environment_variables()
            assert topic_arn is None
            assert len(errors) == 1
            assert "SNS_TOPIC_ARN" in errors[0]

    def test_validate_environment_variables_invalid_minutes(self):
        """Test invalid notification minutes"""
        with patch.dict(os.environ, {
            'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-1:123456789012:calendar-notifications',
            'NOTIFICATION_MINUTES_BEFORE': 'invalid'
        }):
            topic_arn, minutes, errors = validate_environment_variables()
            assert len(errors) == 1
            assert 'valid integer' in errors[0]
            assert minutes == 15  # fallback value

    def test_validate_environment_variables_out_of_range_minutes(self):
        """Test out of range notification minutes"""
        with patch.dict(os.environ, {
            'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-1:123456789012:calendar-notifications',
            'NOTIFICATION_MINUTES_BEFORE': '2000'  # Over 24 hours
        }):
            topic_arn, minutes, errors = validate_environment_variables()
            assert len(errors) == 1
            assert 'between 1 and 1440' in errors[0]

    def test_validate_environment_variables_negative_minutes(self):
        """Test negative notification minutes"""
        with patch.dict(os.environ, {
            'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-1:123456789012:calendar-notifications',
            'NOTIFICATION_MINUTES_BEFORE': '-5'
        }):
            topic_arn, minutes, errors = validate_environment_variables()
            assert len(errors) == 1
            assert 'between 1 and 1440' in errors[0]

    def test_validate_event_payload_success(self):
        """Test successful event payload validation"""
        event = {
            "event_summary": "Team Meeting",
            "event_time": "2024-12-25T10:00:00",
            "notification_type": "calendar_reminder",
        }
        validated_event, errors = validate_event_payload(event)
        assert validated_event == event
        assert errors == []

    def test_validate_event_payload_missing_fields(self):
        """Test missing required fields in event payload"""
        event = {"event_summary": "Meeting"}
        validated_event, errors = validate_event_payload(event)
        assert validated_event is None
        assert len(errors) == 1
        assert "event_time" in errors[0]
        assert "notification_type" in errors[0]


class TestInputSanitization:
    """Test input sanitization functionality"""

    def test_sanitize_event_summary_normal_text(self):
        """Test sanitizing normal event summary"""
        result = sanitize_event_summary("Team Meeting")
        assert result == "Team Meeting"

    def test_sanitize_event_summary_empty_string(self):
        """Test sanitizing empty event summary"""
        result = sanitize_event_summary("")
        assert result == "Untitled Event"

    def test_sanitize_event_summary_whitespace_only(self):
        """Test sanitizing whitespace-only event summary"""
        result = sanitize_event_summary("   \t\n   ")
        assert result == "Untitled Event"

    def test_sanitize_event_summary_with_newlines(self):
        """Test sanitizing event summary with newlines"""
        result = sanitize_event_summary("Line 1\nLine 2\nLine 3")
        assert result == "Line 1 Line 2 Line 3"

    def test_sanitize_event_summary_with_excessive_whitespace(self):
        """Test sanitizing event summary with excessive whitespace"""
        result = sanitize_event_summary("  Multiple   spaces    everywhere  ")
        assert result == "Multiple spaces everywhere"

    def test_sanitize_event_summary_with_tabs(self):
        """Test sanitizing event summary with tabs"""
        result = sanitize_event_summary("Tab\tSeparated\tValues")
        assert result == "Tab Separated Values"

    def test_sanitize_event_summary_with_emojis(self):
        """Test sanitizing event summary preserves emojis"""
        result = sanitize_event_summary("Meeting 📅 at office 🏢")
        assert result == "Meeting 📅 at office 🏢"

    def test_sanitize_event_summary_none_input(self):
        """Test sanitizing None input"""
        result = sanitize_event_summary(None)
        assert result == "Untitled Event"


class TestMessageFormatting:
    """Test message formatting functions"""

    def test_format_notification_message_simple(self):
        """Test simple message formatting"""
        event_data = {
            "event_summary": "Team Meeting",
            "event_time": "2024-12-25T10:00:00",
        }
        message = format_notification_message(event_data, 15)
        assert message == "Team Meeting (15min)"

    def test_format_notification_message_different_minutes(self):
        """Test message formatting with different notification minutes"""
        event_data = {
            "event_summary": "Doctor Appointment",
            "event_time": "2024-12-25T10:00:00",
        }
        message = format_notification_message(event_data, 30)
        assert message == "Doctor Appointment (30min)"

    def test_format_notification_message_long_title(self):
        """Test message formatting with long title that needs truncation"""
        long_title = "This is a very long meeting title that definitely exceeds the SMS character limit and needs to be truncated properly for sure this time with extra words and more text"
        event_data = {"event_summary": long_title, "event_time": "2024-12-25T10:00:00"}
        message = format_notification_message(event_data, 15)

        assert len(message) <= 160
        assert message.endswith("... (15min)")
        assert "This is a very long meeting" in message

    def test_format_notification_message_exactly_160_chars(self):
        """Test message that's exactly at the 160 character limit"""
        # Create a title that results in exactly 160 characters
        title_length = 160 - len(" (15min)")
        exact_title = "A" * title_length
        event_data = {"event_summary": exact_title, "event_time": "2024-12-25T10:00:00"}
        message = format_notification_message(event_data, 15)

        assert len(message) == 160
        assert message == f"{exact_title} (15min)"

    def test_format_notification_message_with_dirty_input(self):
        """Test message formatting with input that needs sanitization"""
        event_data = {
            "event_summary": "  Meeting\nwith\ttabs  and\n\nnewlines  ",
            "event_time": "2024-12-25T10:00:00"
        }
        message = format_notification_message(event_data, 15)

        assert message == "Meeting with tabs and newlines (15min)"

    def test_format_notification_message_empty_summary(self):
        """Test message formatting with empty summary"""
        event_data = {
            "event_summary": "",
            "event_time": "2024-12-25T10:00:00"
        }
        message = format_notification_message(event_data, 15)

        assert message == "Untitled Event (15min)"

    def test_format_notification_message_missing_summary(self):
        """Test message formatting with missing summary field"""
        event_data = {
            "event_time": "2024-12-25T10:00:00"
        }
        message = format_notification_message(event_data, 30)

        assert message == "Untitled Event (30min)"


class TestSNSOperations:
    """Test SNS-related functions"""

    @mock_aws
    def test_send_sms_notification_success(self):
        """Test successful SMS sending"""
        # Create mock SNS topic
        sns = boto3.client("sns", region_name="us-east-1")
        response = sns.create_topic(Name="calendar-notifications")
        topic_arn = response["TopicArn"]

        result = send_sms_notification(sns, topic_arn, "Test message", "Test Subject")

        assert result["status"] == "success"
        assert "message_id" in result
        assert result["sns_response"]["ResponseMetadata"]["HTTPStatusCode"] == 200

    @mock_aws
    def test_send_sms_notification_invalid_topic(self):
        """Test SMS sending with invalid topic ARN"""
        sns = boto3.client("sns", region_name="us-east-1")
        invalid_arn = "arn:aws:sns:us-east-1:123456789012:nonexistent-topic"

        result = send_sms_notification(sns, invalid_arn, "Test message", "Test Subject")

        assert result["status"] == "failed"
        assert "error" in result


class TestNotificationProcessing:
    """Test notification processing logic"""

    @mock_aws
    def test_process_notification_success(self):
        """Test successful notification processing"""
        # Setup SNS
        sns = boto3.client("sns", region_name="us-east-1")
        response = sns.create_topic(Name="calendar-notifications")
        topic_arn = response["TopicArn"]

        event = {
            "event_summary": "Team Meeting",
            "event_time": "2024-12-25T10:00:00",
            "notification_type": "calendar_reminder",
        }

        result = process_notification(event, topic_arn, 15)

        assert result["success"] is True
        assert result["event_summary"] == "Team Meeting"
        assert "message_id" in result
        assert result["message_length"] == len("Team Meeting (15min)")


class TestLambdaHandler:
    """Test the main lambda handler function"""

    @mock_aws
    def test_lambda_handler_success(self):
        """Test successful lambda handler execution"""
        # Setup environment and SNS
        with patch.dict(
            os.environ,
            {
                "SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:calendar-notifications",
                "NOTIFICATION_MINUTES_BEFORE": "15",
            },
        ):
            sns = boto3.client("sns", region_name="us-east-1")
            sns.create_topic(Name="calendar-notifications")

            event = {
                "event_summary": "Team Meeting",
                "event_time": "2024-12-25T10:00:00",
                "notification_type": "calendar_reminder",
            }
            context = {}

            result = lambda_handler(event, context)

            assert result["success"] is True
            assert result["event_summary"] == "Team Meeting"
            assert "message_id" in result

    def test_lambda_handler_missing_env_vars(self):
        """Test lambda handler with missing environment variables"""
        with patch.dict(os.environ, {}, clear=True):
            event = {
                "event_summary": "Meeting",
                "event_time": "2024-12-25T10:00:00",
                "notification_type": "calendar_reminder",
            }
            context = {}

            result = lambda_handler(event, context)

            assert result["success"] is False
            assert "SNS_TOPIC_ARN" in result["error"]

    def test_lambda_handler_missing_event_fields(self):
        """Test lambda handler with missing event fields"""
        with patch.dict(
            os.environ,
            {
                "SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:calendar-notifications"
            },
        ):
            event = {"event_summary": "Meeting"}  # Missing required fields
            context = {}

            result = lambda_handler(event, context)

            assert result["success"] is False
            assert "Missing required fields" in result["error"]

    @mock_aws
    def test_lambda_handler_sns_error(self):
        """Test lambda handler with SNS error"""
        with patch.dict(
            os.environ,
            {
                "SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:nonexistent-topic",
                "NOTIFICATION_MINUTES_BEFORE": "15",
            },
        ):
            event = {
                "event_summary": "Team Meeting",
                "event_time": "2024-12-25T10:00:00",
                "notification_type": "calendar_reminder",
            }
            context = {}

            result = lambda_handler(event, context)

            assert result["success"] is False
            assert "SMS sending failed" in result["error"]

