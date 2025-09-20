# ============================================================================
# IAM Roles and Policies
# ============================================================================

# IAM role for iCal processor Lambda
resource "aws_iam_role" "ical_processor_role" {
  name = "${local.name_prefix}-ical-processor-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# AWS-managed basic execution policy for Lambda
resource "aws_iam_role_policy_attachment" "ical_processor_basic" {
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
  role       = aws_iam_role.ical_processor_role.name
}

# Custom policy for our specific permissions
resource "aws_iam_role_policy" "ical_processor_policy" {
  name = "${local.name_prefix}-ical-processor-policy"
  role = aws_iam_role.ical_processor_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # S3 permissions
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.ical_uploads.arn,
          "${aws_s3_bucket.ical_uploads.arn}/*"
        ]
      },
      # EventBridge Scheduler permissions - properly scoped to our account and region
      {
        Effect = "Allow"
        Action = [
          "scheduler:CreateSchedule",
          "scheduler:DeleteSchedule"
        ]
        Resource = "arn:aws:scheduler:${var.aws_region}:${data.aws_caller_identity.current.account_id}:schedule/${local.schedule_group}/*"
      },
      # Schedule group management
      {
        Effect = "Allow"
        Action = [
          "scheduler:CreateScheduleGroup",
          "scheduler:DeleteScheduleGroup"
        ]
        Resource = "arn:aws:scheduler:${var.aws_region}:${data.aws_caller_identity.current.account_id}:schedule-group/${local.schedule_group}"
      },
      # PassRole permission to delegate the EventBridge scheduler role
      # This allows the Lambda to tell EventBridge "use this role when executing schedules"
      { Effect = "Allow"
        Action = [
          "iam:PassRole"
        ]
        Resource = aws_iam_role.eventbridge_scheduler_role.arn
      }
    ]
  })
}

# ============================================================================
# Notification Service IAM Resources
# ============================================================================

# IAM role for notification service Lambda
resource "aws_iam_role" "notification_service_role" {
  name = "${local.name_prefix}-notification-service-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# Basic execution policy
resource "aws_iam_role_policy_attachment" "notification_service_basic" {
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
  role       = aws_iam_role.notification_service_role.name
}

# SNS publishing permissions
resource "aws_iam_role_policy" "notification_service_policy" {
  name = "${local.name_prefix}-notification-service-policy"
  role = aws_iam_role.notification_service_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = aws_sns_topic.calendar_notifications.arn
      }
    ]
  })
}

