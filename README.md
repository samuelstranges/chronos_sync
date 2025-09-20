# Chronos Sync

AWS serverless app that sends SMS notifications 15 minutes before calendar events.

## How it works

1. Upload `.ics` calendar files
2. Lambda processes events and creates schedules
3. Get SMS notifications before meetings

## Architecture

- **AWS Lambda** (Python) with shared dependency layer
- **EventBridge Scheduler** for precise timing
- **SNS** for SMS notifications
- **Terraform** for infrastructure

## Setup

```bash
cd terraform/environments/dev
terraform init
terraform apply
```

Built with Lambda layers for fast deployments (5KB functions vs 45MB).