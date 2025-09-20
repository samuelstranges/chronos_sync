locals {
  project_name    = "ical-sync"
  environment     = "dev"
  name_prefix     = "${local.project_name}-${local.environment}"
  schedule_group  = "ical-notifications"
}

terraform {
  required_version = ">= 1.0"

  # Store state in separate infrastructure repo outside main codebase
  # This keeps sensitive infrastructure data separate from application code
  backend "local" {
    path = "/Users/computer/Documents/Git/chronos-sync-infrastructure/dev/terraform.tfstate"
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }

    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }

    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = local.project_name
      Environment = local.environment
      ManagedBy   = "terraform"

    }
  }
}

# ============================================================================
# Core Project Configuration
# ============================================================================
#
# This file contains the foundational Terraform configuration:
# - Provider settings
# - Local values
# - Basic project setup
#
# Resources are organized in separate files:
# - s3.tf: S3 storage resources
# - iam.tf: IAM roles and policies
# - lambda.tf: Lambda functions
# ============================================================================

# Get current AWS account ID
data "aws_caller_identity" "current" {}
