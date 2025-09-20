import boto3
import recurring_ical_events
import os
import base64
import zipfile
import io
import json
import pytz
from datetime import datetime, timedelta
from icalendar import Calendar


def get_upcoming_events(ical_content, days_ahead=7):
    """
    Extract upcoming events from iCal content.

    TIMEZONE HANDLING NOTE:
    =======================
    The recurring_ical_events library returns events with their original datetime
    types from the calendar file. This can be:
    - Timezone-aware datetimes (with .tzinfo set)
    - Naive datetimes (no timezone info - common in exported .ics files)

    When calendar apps export .ics files, they often strip timezone information
    to make files "portable". These naive datetimes should be interpreted in the
    user's local timezone, not UTC. The timezone conversion is handled later in
    create_event_schedule() function.
    """
    # Parse the calendar
    cal = Calendar.from_ical(ical_content)

    # Define time window - let recurring_ical_events handle timezone complexity
    # Note: start_date here is in UTC (Lambda environment timezone)
    # but this is just for the search window, not event interpretation
    start_date = datetime.now()
    end_date = start_date + timedelta(days=days_ahead)

    print(f"=== DEBUG: Event extraction window ===")
    print(f"Current time: {start_date}")
    print(f"Search window: {start_date} to {end_date}")

    # Get events in time window - library handles all complexity!
    events = recurring_ical_events.of(cal).between(start_date, end_date)

    print(f"Found {len(events)} raw events from calendar")

    # Convert to our format
    upcoming_events = []
    for event in events:
        start_dt = event["DTSTART"].dt

        # Skip all-day events (datetime.date objects)
        # All-day events like birthdays, holidays don't need time-based notifications
        # They use datetime.date objects which don't have timestamp() method
        if not hasattr(start_dt, 'timestamp'):
            print(f"Skipping all-day event: {event.get('SUMMARY', 'Untitled Event')}")
            continue

        event_info = {
            "summary": str(event.get("SUMMARY", "Untitled Event")),
            "start_datetime": start_dt,
            "location": str(event.get("LOCATION", "")),
            "description": str(event.get("DESCRIPTION", "")),
            "uid": str(event.get("UID", "")),
        }
        upcoming_events.append(event_info)

    return upcoming_events


def validate_environment_variables():
    """
    Validate required environment variables
    """
    bucket_name = os.environ.get("S3_BUCKET_NAME")
    schedule_group = os.environ.get("SCHEDULE_GROUP_NAME")

    errors = []
    if not bucket_name:
        errors.append("S3_BUCKET_NAME environment variable not set")
    if not schedule_group:
        errors.append("SCHEDULE_GROUP_NAME environment variable not set")

    return bucket_name, schedule_group, errors


def validate_event_payload(event):
    """
    Validate event payload contains required fields
    """
    zip_file_b64 = event.get("zip_file")

    if not zip_file_b64:
        return None, ["zip_file required in event payload"]

    return zip_file_b64, []


def lambda_handler(event, context):
    """
    Process all iCal files in S3 bucket and create notification schedules
    """
    # Validate environment variables
    bucket_name, schedule_group, env_errors = validate_environment_variables()
    if env_errors:
        return {"error": env_errors[0], "success": False}

    # Validate event payload
    zip_file_b64, payload_errors = validate_event_payload(event)
    if payload_errors:
        return {"error": payload_errors[0], "success": False}

    try:
        # Step 1: Clear existing EventBridge schedules
        print("Clearing existing schedules...")
        clear_event_bridge_schedules()

        # Step 2: Clear S3 bucket
        print("Clearing S3 bucket...")
        files_deleted = clear_bucket(bucket_name)

        # Step 3: Extract and upload calendar files from zip
        print("Processing zip file...")
        ical_files = extract_and_upload_calendars(zip_file_b64, bucket_name)

        # Step 4: Process calendar files and create schedules
        print("Creating schedules...")
        total_events = process_calendars_and_create_schedules(
            bucket_name, schedule_group
        )

        return {
            "message": "Calendar processing completed successfully",
            "bucket_name": bucket_name,
            "schedule_group": schedule_group,
            "files_deleted": files_deleted,
            "calendars_processed": len(ical_files),
            "total_events": total_events,
            "schedules_cleared": True,
            "success": True,
        }

    except Exception as e:
        print(f"Lambda execution failed: {str(e)}")
        return {"error": str(e), "success": False}


def ensure_schedule_group_exists(scheduler, schedule_group):
    """
    Ensure schedule group exists, handling the case where it already exists
    """
    try:
        scheduler.create_schedule_group(Name=schedule_group)
        print(f"Created schedule group: {schedule_group}")
    except scheduler.exceptions.ConflictException:
        print(f"Schedule group {schedule_group} already exists - continuing")
    except Exception as e:
        print(f"Error creating schedule group: {str(e)}")
        raise


def clear_event_bridge_schedules():
    """
    Delete all existing EventBridge schedules from our schedule group
    """
    scheduler = boto3.client("scheduler")
    schedule_group = os.environ.get("SCHEDULE_GROUP_NAME", "ical-notifications")

    try:
        # Delete the entire group (deletes all schedules)
        scheduler.delete_schedule_group(Name=schedule_group)
        print(f"Deleted schedule group: {schedule_group}")

        # Wait for deletion to complete (EventBridge group deletion is async)
        import time
        print("Waiting 30 seconds for schedule group deletion to complete...")
        time.sleep(30)

        # Recreate the empty group for new schedules
        ensure_schedule_group_exists(scheduler, schedule_group)

        return True

    except (scheduler.exceptions.ResourceNotFoundException, KeyError):
        # Schedule group doesn't exist - create new one
        # Note: KeyError is caught for moto compatibility (moto throws KeyError instead of ResourceNotFoundException)
        print("Schedule group doesn't exist - creating new one")
        ensure_schedule_group_exists(scheduler, schedule_group)
        return True


def clear_bucket(bucket_name):
    """
    Delete all files from the S3 bucket
    """
    s3 = boto3.resource("s3")
    bucket = s3.Bucket(bucket_name)

    try:
        # Count objects before deletion
        object_count = sum(1 for _ in bucket.objects.all())

        if object_count == 0:
            print("Bucket already empty")
            return 0

        # Delete all objects - handles pagination automatically
        bucket.objects.all().delete()

        print(f"Deleted {object_count} files from bucket")
        return object_count

    except Exception as e:
        print(f"Error clearing bucket: {str(e)}")
        raise


def decode_zip_file(zip_file_b64):
    """
    Decode base64 zip file and return BytesIO buffer
    """
    zip_data = base64.b64decode(zip_file_b64)
    return io.BytesIO(zip_data)


def extract_ical_files_from_zip(zip_buffer):
    """
    Extract .ics files from zip buffer and return list of (filename, content) tuples
    """
    ical_files = []

    with zipfile.ZipFile(zip_buffer) as zip_ref:
        for filename in zip_ref.namelist():
            if filename.endswith(".ics") and not filename.endswith("/"):
                ical_content = zip_ref.read(filename)
                ical_files.append((filename, ical_content))

    return ical_files


def upload_ical_file_to_s3(s3_client, content, bucket_name, filename):
    """
    Upload a single iCal file to S3
    """
    file_buffer = io.BytesIO(content)
    s3_client.upload_fileobj(
        file_buffer,
        bucket_name,
        filename,
        ExtraArgs={"ContentType": "text/calendar"},
    )


def extract_and_upload_calendars(zip_file_b64, bucket_name):
    """
    Extract .ics files from base64 zip and upload to S3 using streaming
    """
    s3 = boto3.client("s3")

    # Decode base64 zip file
    zip_buffer = decode_zip_file(zip_file_b64)

    # Extract iCal files from zip
    ical_files_data = extract_ical_files_from_zip(zip_buffer)

    # Upload each file to S3
    uploaded_files = []
    for filename, content in ical_files_data:
        upload_ical_file_to_s3(s3, content, bucket_name, filename)
        uploaded_files.append(filename)
        print(f"Uploaded {filename} to S3")

    return uploaded_files


def list_ical_files_in_bucket(s3_client, bucket_name):
    """
    List all .ics files in S3 bucket
    """
    response = s3_client.list_objects_v2(Bucket=bucket_name)

    if 'Contents' not in response:
        return []

    ical_files = []
    for obj in response['Contents']:
        filename = obj.get('Key')
        if filename and filename.endswith('.ics'):
            ical_files.append(filename)

    return ical_files


def download_ical_content(s3_client, bucket_name, filename):
    """
    Download iCal file content from S3
    """
    file_response = s3_client.get_object(Bucket=bucket_name, Key=filename)
    return file_response['Body'].read()


def create_schedules_for_events(events, schedule_group):
    """
    Create EventBridge schedules for a list of events
    """
    schedules_created = 0
    for event in events:
        create_event_schedule(event, schedule_group)
        schedules_created += 1
    return schedules_created


def process_calendars_and_create_schedules(bucket_name, schedule_group):
    """
    Download calendar files from S3, extract events, and create schedules
    """
    s3 = boto3.client("s3")

    # List all .ics files in bucket
    ical_files = list_ical_files_in_bucket(s3, bucket_name)

    if not ical_files:
        print("No calendar files found in bucket")
        return 0

    total_events = 0

    for filename in ical_files:
        # Download file content
        ical_content = download_ical_content(s3, bucket_name, filename)

        # Extract upcoming events
        events = get_upcoming_events(ical_content, days_ahead=7)

        # Create EventBridge schedules for each event
        schedules_created = create_schedules_for_events(events, schedule_group)

        total_events += len(events)
        print(f"Processed {filename}: {len(events)} events found")

    return total_events


def get_schedule_configuration():
    """
    Get schedule configuration from environment variables
    """
    notification_lambda_arn = os.environ.get('NOTIFICATION_LAMBDA_ARN')
    scheduler_role_arn = os.environ.get('SCHEDULER_ROLE_ARN')
    notification_minutes = int(os.environ.get('NOTIFICATION_MINUTES_BEFORE', '15'))
    fallback_timezone = os.environ.get('FALLBACK_TIMEZONE', 'UTC')

    if not notification_lambda_arn or not scheduler_role_arn:
        raise ValueError("NOTIFICATION_LAMBDA_ARN and SCHEDULER_ROLE_ARN environment variables are required")

    return notification_lambda_arn, scheduler_role_arn, notification_minutes, fallback_timezone


def generate_schedule_name(event):
    """
    Generate unique schedule name for an event
    """
    return f"event-{event['uid']}-{int(event['start_datetime'].timestamp())}"


def calculate_notification_time(event_time, minutes_before):
    """
    Calculate notification time based on event time and minutes before
    """
    return event_time - timedelta(minutes=minutes_before)


def build_schedule_payload(event):
    """
    Build the JSON payload for the schedule target
    """
    return json.dumps({
        'event_summary': event['summary'],
        'event_location': event['location'],
        'event_time': event['start_datetime'].isoformat(),
        'notification_type': 'calendar_reminder'
    })


def create_event_schedule(event, schedule_group):
    """
    Create an EventBridge schedule for a single calendar event.

    CRITICAL TIMEZONE BUG FIX:
    ==========================
    This function handles a common timezone issue in calendar applications:

    Problem: Calendar events often have "naive" datetimes (no timezone info).
    When our Lambda (running in UTC) compares these against datetime.now() (UTC),
    it incorrectly assumes naive times are also UTC, causing past events to be
    scheduled as if they were future events.

    Example of the bug:
    - Event time: 9:15 AM (naive, actually Melbourne time)
    - Lambda time: 11:49 PM UTC (which is 9:49 AM Melbourne next day)
    - Comparison: 9:15 <= 23:49 = False (incorrectly thinks event is future)
    - Reality: 9:15 AM Melbourne = 11:15 PM UTC (already passed!)

    Solution: Convert naive times to user's timezone, then to UTC for comparison.
    """
    scheduler = boto3.client("scheduler")

    # Get configuration
    notification_lambda_arn, scheduler_role_arn, notification_minutes, fallback_timezone = get_schedule_configuration()

    # Generate unique schedule name
    schedule_name = generate_schedule_name(event)

    # Calculate notification time
    notification_time = calculate_notification_time(event['start_datetime'], notification_minutes)

    # DEBUG: Log all time-related info
    print(f"=== DEBUG: Time validation for {event['summary']} ===")
    print(f"Event start time: {event['start_datetime']} (tzinfo: {event['start_datetime'].tzinfo})")
    print(f"Notification time: {notification_time} (tzinfo: {notification_time.tzinfo})")

    # TIMEZONE HANDLING DOCUMENTATION:
    # ================================
    # Calendar events can have three types of datetime information:
    # 1. Timezone-aware: DTSTART;TZID=Australia/Melbourne:20250919T091500
    # 2. UTC with Z suffix: DTSTART:20250919T231500Z
    # 3. Naive/floating: DTSTART:20250919T091500 (no timezone info)
    #
    # The problem: When calendar apps export .ics files, they often strip timezone
    # info to make files "portable", resulting in naive datetimes. These should be
    # interpreted in the user's local timezone, not UTC.
    #
    # Our Lambda runs in UTC, so datetime.now() returns UTC time. If we compare
    # a naive Melbourne time (9:15 AM) against UTC time (11:49 PM previous day),
    # Python treats them as the same timezone and thinks 9:15 AM is "future"
    # when it's actually 34 minutes in the past!
    #
    # Solution: Convert naive times to the user's timezone, then to UTC for comparison.

    # Validate notification time is in the future
    if notification_time.tzinfo:
        # Case 1: Timezone-aware notification time
        # Compare directly with UTC (both have timezone info)
        current_time = datetime.now(tz=pytz.UTC)
        print(f"Using timezone-aware comparison with UTC: {current_time}")
    else:
        # Case 2: Naive notification time (no timezone info)
        # Assume it's in the user's local timezone and convert to UTC for comparison
        # This follows the "principle of least surprise" - users expect naive times
        # to be in their local timezone, not UTC
        fallback_tz = pytz.timezone(fallback_timezone)

        # Step 1: Localize naive time to user's timezone
        notification_time_tz = fallback_tz.localize(notification_time)

        # Step 2: Convert to UTC for comparison with Lambda's current time
        notification_time_utc = notification_time_tz.astimezone(pytz.UTC)
        current_time = datetime.now(tz=pytz.UTC)

        print(f"Converted naive time {notification_time} ({fallback_timezone}) to UTC: {notification_time_utc}")
        print(f"Current time (UTC): {current_time}")

        # Update notification_time for the comparison
        notification_time = notification_time_utc

    print(f"Comparison: {notification_time} <= {current_time} = {notification_time <= current_time}")

    if notification_time <= current_time:
        print(f"✅ SKIPPING past event: {event['summary']} (notification time: {notification_time})")
        return
    else:
        print(f"⚠️ SCHEDULING future event: {event['summary']} (notification time: {notification_time})")

    # Create schedule expression with proper timezone handling
    #
    # AWS EventBridge Scheduler Requirements:
    # ======================================
    # - Schedule expression format: at(YYYY-MM-DDTHH:MM:SS) - NO timezone in string
    # - Timezone specified separately in ScheduleExpressionTimezone parameter
    # - Including timezone indicators like 'Z' or '+10:00' in the datetime string
    #   will cause "ValidationException: Invalid Schedule Expression"
    #
    # This is why we strip timezone info from the datetime and pass it separately.

    if notification_time.tzinfo:
        # Event has timezone info - extract timezone name and convert to UTC datetime
        timezone_name = str(notification_time.tzinfo)
        # Convert to naive datetime in original timezone for schedule expression
        naive_time = notification_time.replace(tzinfo=None)
        schedule_expression = f"at({naive_time.strftime('%Y-%m-%dT%H:%M:%S')})"
        schedule_timezone = timezone_name
    else:
        # No timezone info - apply fallback timezone
        schedule_expression = f"at({notification_time.strftime('%Y-%m-%dT%H:%M:%S')})"
        schedule_timezone = fallback_timezone

    # Build payload
    payload = build_schedule_payload(event)

    try:
        scheduler.create_schedule(
            Name=schedule_name,
            GroupName=schedule_group,
            ScheduleExpression=schedule_expression,
            ScheduleExpressionTimezone=schedule_timezone,
            Target={
                'Arn': notification_lambda_arn,
                'RoleArn': scheduler_role_arn,
                'Input': payload
            },
            FlexibleTimeWindow={'Mode': 'OFF'}
        )

        print(f"Created schedule: {schedule_name} at {schedule_expression} in {schedule_timezone}")

    except Exception as e:
        print(f"Failed to create schedule for {event['summary']}: {str(e)}")
        raise
