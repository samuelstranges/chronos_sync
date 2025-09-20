#!/bin/bash

# Simple calendar upload script
# Usage: ./upload_calendars.sh <directory_path>

if [ $# -ne 1 ]; then
    echo "Usage: $0 <directory_path>"
    exit 1
fi

CALENDAR_DIR="$1"

if [ ! -d "$CALENDAR_DIR" ]; then
    echo "Error: Directory '$CALENDAR_DIR' does not exist"
    exit 1
fi

echo "Processing calendar directory: $CALENDAR_DIR"

# Find .ics files
ICS_FILES=$(find "$CALENDAR_DIR" -name "*.ics" -type f)

if [ -z "$ICS_FILES" ]; then
    echo "Error: No .ics files found in directory"
    exit 1
fi

echo "Found $(echo "$ICS_FILES" | wc -l | tr -d ' ') .ics files"

# Create zip file
ZIP_FILE="/tmp/calendars.zip"
rm -f "$ZIP_FILE"  # Remove any existing zip file
cd "$CALENDAR_DIR"
zip -r "$ZIP_FILE" *.ics >/dev/null 2>&1

if [ ! -f "$ZIP_FILE" ]; then
    echo "Error: Failed to create zip file"
    exit 1
fi

# Base64 encode (macOS compatible)
BASE64_ZIP=$(base64 -i "$ZIP_FILE")

# Create payload
echo '{"zip_file": "'"$BASE64_ZIP"'"}' > /tmp/payload.json

# Invoke Lambda
echo "Invoking Lambda function..."
aws lambda invoke \
    --function-name ical-sync-dev-ical-processor \
    --payload file:///tmp/payload.json \
    --cli-binary-format raw-in-base64-out \
    response.json

# Show response
echo "Response:"
cat response.json

# Cleanup
rm -f "$ZIP_FILE" /tmp/payload.json response.json