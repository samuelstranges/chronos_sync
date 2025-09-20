# ============================================================================
# Configuration Variables
# ============================================================================

variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "fallback_timezone" {
  description = "Default timezone when iCal events don't specify one"
  type        = string
  default     = "Australia/Melbourne"
}

variable "notification_minutes_before" {
  description = "Minutes before event to send notification"
  type        = number
  default     = 15
}

variable "lambda_memory_size" {
  description = "Memory allocated to Lambda functions (MB)"
  type        = number
  default     = 512
}

variable "lambda_timeout" {
  description = "Lambda function timeout (seconds)"
  type        = number
  default     = 300
}

variable "phone_number" {
  description = "Phone number for SMS notifications (E.164 format: +61400000000)"
  type        = string
}

