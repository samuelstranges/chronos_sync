# Chronos Sync Agent Guidelines

## Build/Lint/Test Commands

- **Single test**:
  `python -m pytest src/lambda_functions/ical_processor/test_lambda.py::TestClassName::test_method_name -v`
- **All tests**: `python -m pytest src/lambda_functions/*/test_lambda.py -v`
- **Install deps**:
  `pip install -r src/lambda_functions/ical_processor/requirements.txt && pip install -r src/lambda_functions/notification_service/requirements.txt`

# Code Style Guidelines

- **Naming**: snake_case for functions/variables, PascalCase for classes,
  ALL_CAPS for constants
- **Line length**: 100 characters maximum
- **Type hints**: Required for function parameters and return values
- **Imports**: Group as standard library, third-party, local; use absolute
  imports
- **Error handling**: Validate env vars and payloads first, return
  `{"success": False, "error": "message"}`
- **AWS patterns**: Use boto3 clients, mock with moto, handle
  ResourceNotFoundException, stream S3 operations
- **Lambda structure**: `lambda_handler(event, context)` → validate env →
  validate payload → process → return structured response
- **Testing**: pytest + moto, test success/error cases, mock env vars with
  `patch.dict(os.environ, {...})`

