import boto3
import json
import os
from typing import Dict


def validate_environment_variables():
    """
    Validate required environment variables for notification service
    """
    sns_topic_arn = os.environ.get("SNS_TOPIC_ARN")
    notification_minutes_str = os.environ.get("NOTIFICATION_MINUTES_BEFORE", "15")

    errors = []
    if not sns_topic_arn:
        errors.append("SNS_TOPIC_ARN environment variable not set")

    try:
        notification_minutes = int(notification_minutes_str)
        if notification_minutes <= 0 or notification_minutes > 1440:  # Max 24 hours
            errors.append("NOTIFICATION_MINUTES_BEFORE must be between 1 and 1440")
    except ValueError:
        errors.append("NOTIFICATION_MINUTES_BEFORE must be a valid integer")
        notification_minutes = 15  # fallback

    return sns_topic_arn, notification_minutes, errors


def validate_event_payload(event):
    """
    Validate EventBridge event payload contains required notification fields
    """
    required_fields = ["event_summary", "event_time", "notification_type"]
    missing_fields = []

    for field in required_fields:
        if field not in event:
            missing_fields.append(field)

    if missing_fields:
        return None, [f"Missing required fields: {', '.join(missing_fields)}"]

    return event, []


def sanitize_event_summary(summary: str) -> str:
    """
    Sanitize event summary for SMS - remove problematic characters
    """
    if not summary or not summary.strip():
        return "Untitled Event"

    # Remove newlines, tabs, and excessive whitespace
    cleaned = " ".join(summary.strip().split())

    # Remove non-printable characters but keep emojis
    cleaned = "".join(char for char in cleaned if char.isprintable() or ord(char) > 127)

    return cleaned


def format_notification_message(event_data: Dict, notification_minutes: int) -> str:
    """
    Format event data into concise SMS message: "Title (15min)"
    """
    raw_summary = event_data.get("event_summary", "")
    event_summary = sanitize_event_summary(raw_summary)
    suffix = f" ({notification_minutes}min)"

    # Check if we need to truncate
    if len(event_summary) + len(suffix) > 160:
        max_title_length = 160 - len(suffix) - 3  # Reserve space for "..."
        truncated_title = event_summary[:max_title_length] + "..."
        message = f"{truncated_title}{suffix}"
    else:
        message = f"{event_summary}{suffix}"

    return message


def send_sms_notification(
    sns_client, topic_arn: str, message: str, subject: str = "Calendar Reminder"
) -> Dict:
    """
    Send SMS notification via SNS topic
    """
    try:
        response = sns_client.publish(
            TopicArn=topic_arn, Message=message, Subject=subject
        )

        return {
            "status": "success",
            "message_id": response["MessageId"],
            "sns_response": response,
        }

    except Exception as e:
        return {"status": "failed", "error": str(e)}


def process_notification(event, sns_topic_arn, notification_minutes):
    """
    Process the notification by formatting message and sending SMS
    """
    sns = boto3.client("sns")
    message = format_notification_message(event, notification_minutes)

    print(f"Formatted message ({len(message)} chars): {message}")

    result = send_sms_notification(sns, sns_topic_arn, message, "Calendar Reminder")

    if result["status"] == "success":
        print(f"SMS sent successfully. Message ID: {result['message_id']}")
        return {
            "message": "Notification sent successfully",
            "event_summary": event["event_summary"],
            "message_id": result["message_id"],
            "message_length": len(message),
            "success": True,
        }
    else:
        print(f"Failed to send SMS: {result['error']}")
        return {"error": f"SMS sending failed: {result['error']}", "success": False}


def lambda_handler(event, context):
    """
    Handle EventBridge schedule notifications by sending SMS via SNS
    """
    print(f"Received event: {json.dumps(event, default=str)}")

    # Validate environment variables
    sns_topic_arn, notification_minutes, env_errors = validate_environment_variables()
    if env_errors:
        return {"error": env_errors[0], "success": False}

    # Validate event payload
    validated_event, payload_errors = validate_event_payload(event)
    if payload_errors:
        return {"error": payload_errors[0], "success": False}

    try:
        return process_notification(
            validated_event, sns_topic_arn, notification_minutes
        )
    except Exception as e:
        print(f"Lambda execution failed: {str(e)}")
        return {"error": str(e), "success": False}

