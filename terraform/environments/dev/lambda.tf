# ============================================================================
# Lambda Layers
# ============================================================================

# Create Lambda layer for shared Python dependencies
# This layer contains all the heavy dependencies like boto3, icalendar, pytz, etc.
resource "null_resource" "build_python_dependencies_layer" {
  triggers = {
    # Re-build layer when requirements change
    ical_requirements = filemd5("../../../src/lambda_functions/ical_processor/requirements.txt")
    notification_requirements = filemd5("../../../src/lambda_functions/notification_service/requirements.txt")
  }

  provisioner "local-exec" {
    command = <<-EOT
      # Create temporary build directory
      BUILD_DIR=$(mktemp -d)
      mkdir -p $BUILD_DIR/python

      # Install all dependencies into the python directory (required structure for layers)
      python3 -m pip install -r ../../../src/lambda_functions/ical_processor/requirements.txt -t $BUILD_DIR/python
      python3 -m pip install -r ../../../src/lambda_functions/notification_service/requirements.txt -t $BUILD_DIR/python

      # Create .temp directory if it doesn't exist
      mkdir -p .temp

      # Create layer zip file
      cd $BUILD_DIR && zip -r ${path.cwd}/.temp/python-dependencies-layer.zip python/

      # Clean up temporary directory
      rm -rf $BUILD_DIR
    EOT
  }
}

# Lambda layer resource
resource "aws_lambda_layer_version" "python_dependencies" {
  filename            = ".temp/python-dependencies-layer.zip"
  layer_name          = "${local.name_prefix}-python-dependencies"
  compatible_runtimes = ["python3.9", "python3.12"]

  description = "Shared Python dependencies for chronos-sync Lambda functions (boto3, icalendar, pytz, etc.)"

  depends_on = [null_resource.build_python_dependencies_layer]
}

# ============================================================================
# Lambda Functions
# ============================================================================

# Create deployment package for iCal processor (just the source code)
data "archive_file" "ical_processor_zip" {
  type        = "zip"
  source_dir  = "../../../src/lambda_functions/ical_processor"
  output_path = ".temp/ical_processor.zip"
  excludes    = ["venv", "__pycache__", "*.pyc", ".pytest_cache", "test_*.py", "requirements.txt"]
}

# The actual iCal processor Lambda function
resource "aws_lambda_function" "ical_processor" {
  filename      = data.archive_file.ical_processor_zip.output_path
  function_name = "${local.name_prefix}-ical-processor"
  role          = aws_iam_role.ical_processor_role.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.9"

  source_code_hash = data.archive_file.ical_processor_zip.output_base64sha256

  # Attach the shared dependencies layer
  layers = [aws_lambda_layer_version.python_dependencies.arn]

  memory_size = var.lambda_memory_size
  timeout     = var.lambda_timeout

  environment {
    variables = {
      S3_BUCKET_NAME              = aws_s3_bucket.ical_uploads.id
      SCHEDULE_GROUP_NAME         = local.schedule_group
      FALLBACK_TIMEZONE           = var.fallback_timezone
      NOTIFICATION_MINUTES_BEFORE = tostring(var.notification_minutes_before)
      NOTIFICATION_LAMBDA_ARN     = aws_lambda_function.notification_service.arn
      SCHEDULER_ROLE_ARN         = aws_iam_role.eventbridge_scheduler_role.arn
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.ical_processor_basic,
    aws_iam_role_policy.ical_processor_policy,
  ]
}

# ============================================================================
# Notification Service Lambda
# ============================================================================

# Create deployment package for notification service (just the source code)
data "archive_file" "notification_service_zip" {
  type        = "zip"
  source_dir  = "../../../src/lambda_functions/notification_service"
  output_path = ".temp/notification_service.zip"
  excludes    = ["venv", "__pycache__", "*.pyc", ".pytest_cache", "test_*.py", "requirements.txt"]
}

# The notification service Lambda function
resource "aws_lambda_function" "notification_service" {
  filename      = data.archive_file.notification_service_zip.output_path
  function_name = "${local.name_prefix}-notification-service"
  role          = aws_iam_role.notification_service_role.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.9"

  source_code_hash = data.archive_file.notification_service_zip.output_base64sha256

  # Attach the shared dependencies layer
  layers = [aws_lambda_layer_version.python_dependencies.arn]

  memory_size = var.lambda_memory_size
  timeout     = var.lambda_timeout

  environment {
    variables = {
      SNS_TOPIC_ARN = aws_sns_topic.calendar_notifications.arn
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.notification_service_basic,
    aws_iam_role_policy.notification_service_policy,
  ]
}

