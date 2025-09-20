# ============================================================================
# S3 Storage Resources
# ============================================================================

resource "aws_s3_bucket" "ical_uploads" {
  bucket = "${local.name_prefix}-uploads-${random_id.bucket_suffix.hex}"
}

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

# ============================================================================
# SNS Topic for Notifications
# ============================================================================

resource "aws_sns_topic" "calendar_notifications" {
  name = "${local.name_prefix}-calendar-notifications"
}

# SMS subscription for notifications
resource "aws_sns_topic_subscription" "sms_notifications" {
  topic_arn = aws_sns_topic.calendar_notifications.arn
  protocol  = "sms"
  endpoint  = var.phone_number
}