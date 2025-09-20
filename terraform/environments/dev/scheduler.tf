# ============================================================================
# EventBridge Scheduler Resources
# ============================================================================

# Schedule group for organizing our calendar schedules
resource "aws_scheduler_schedule_group" "ical_notifications" {
  name = local.schedule_group
}

# ============================================================================
# EventBridge IAM Role for Invoking Notification Lambda
# ============================================================================

# IAM role for EventBridge Scheduler to invoke our notification Lambda
resource "aws_iam_role" "eventbridge_scheduler_role" {
  name = "${local.name_prefix}-eventbridge-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "scheduler.amazonaws.com"
        }
      }
    ]
  })
}

# Policy for EventBridge to invoke our notification Lambda
resource "aws_iam_role_policy" "eventbridge_scheduler_policy" {
  name = "${local.name_prefix}-eventbridge-scheduler-policy"
  role = aws_iam_role.eventbridge_scheduler_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = aws_lambda_function.notification_service.arn
      }
    ]
  })
}