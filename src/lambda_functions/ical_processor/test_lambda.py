import pytest
import json
import base64
import zipfile
import io
import os
import boto3
import pytz
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from moto import mock_aws
from lambda_function import (
    get_upcoming_events,
    validate_environment_variables,
    validate_event_payload,
    decode_zip_file,
    extract_ical_files_from_zip,
    upload_ical_file_to_s3,
    list_ical_files_in_bucket,
    download_ical_content,
    generate_schedule_name,
    calculate_notification_time,
    build_schedule_payload,
    get_schedule_configuration,
    create_event_schedule,
    lambda_handler
)

class TestICalProcessing:
    """Test suite for iCal processing functionality"""

    def test_basic_event_parsing(self):
        """Test parsing a simple event happening tomorrow"""
        tomorrow = datetime.now() + timedelta(days=1)
        tomorrow_str = tomorrow.strftime("%Y%m%dT%H%M%SZ")

        test_ical = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
DTSTART:{tomorrow_str}
DTEND:{tomorrow_str.replace('T10', 'T11')}
SUMMARY:Test Meeting Tomorrow
LOCATION:Conference Room A
UID:test-001@example.com
END:VEVENT
END:VCALENDAR"""

        events = get_upcoming_events(test_ical, days_ahead=7)

        assert len(events) == 1
        assert events[0]['summary'] == 'Test Meeting Tomorrow'
        assert events[0]['location'] == 'Conference Room A'
        assert events[0]['uid'] == 'test-001@example.com'

    def test_past_events_filtered_out(self):
        """Test that past events are not included"""
        yesterday = datetime.now() - timedelta(days=1)
        yesterday_str = yesterday.strftime("%Y%m%dT%H%M%SZ")

        test_ical = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
DTSTART:{yesterday_str}
DTEND:{yesterday_str.replace('T10', 'T11')}
SUMMARY:Past Meeting
UID:past-001@example.com
END:VEVENT
END:VCALENDAR"""

        events = get_upcoming_events(test_ical, days_ahead=7)

        assert len(events) == 0

    def test_events_beyond_window_filtered_out(self):
        """Test that events beyond the time window are filtered out"""
        far_future = datetime.now() + timedelta(days=10)
        far_future_str = far_future.strftime("%Y%m%dT%H%M%SZ")

        test_ical = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
DTSTART:{far_future_str}
DTEND:{far_future_str.replace('T10', 'T11')}
SUMMARY:Far Future Meeting
UID:future-001@example.com
END:VEVENT
END:VCALENDAR"""

        events = get_upcoming_events(test_ical, days_ahead=7)

        assert len(events) == 0

    def test_empty_calendar(self):
        """Test handling of empty calendar"""
        test_ical = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
END:VCALENDAR"""

        events = get_upcoming_events(test_ical, days_ahead=7)

        assert len(events) == 0

    def test_multiple_events_in_window(self):
        """Test multiple events within the time window"""
        day1 = datetime.now() + timedelta(days=1)
        day3 = datetime.now() + timedelta(days=3)
        day5 = datetime.now() + timedelta(days=5)

        day1_str = day1.strftime("%Y%m%dT%H%M%SZ")
        day3_str = day3.strftime("%Y%m%dT%H%M%SZ")
        day5_str = day5.strftime("%Y%m%dT%H%M%SZ")

        test_ical = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
DTSTART:{day1_str}
DTEND:{day1_str.replace('T10', 'T11')}
SUMMARY:Meeting Day 1
UID:day1-001@example.com
END:VEVENT
BEGIN:VEVENT
DTSTART:{day3_str}
DTEND:{day3_str.replace('T14', 'T15')}
SUMMARY:Meeting Day 3
UID:day3-001@example.com
END:VEVENT
BEGIN:VEVENT
DTSTART:{day5_str}
DTEND:{day5_str.replace('T16', 'T17')}
SUMMARY:Meeting Day 5
UID:day5-001@example.com
END:VEVENT
END:VCALENDAR"""

        events = get_upcoming_events(test_ical, days_ahead=7)

        assert len(events) == 3
        summaries = [event['summary'] for event in events]
        assert 'Meeting Day 1' in summaries
        assert 'Meeting Day 3' in summaries
        assert 'Meeting Day 5' in summaries

    def test_different_time_windows(self):
        """Test different days_ahead parameters"""
        day2 = datetime.now() + timedelta(days=2)
        day2_str = day2.strftime("%Y%m%dT%H%M%SZ")

        test_ical = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
DTSTART:{day2_str}
DTEND:{day2_str.replace('T10', 'T11')}
SUMMARY:Meeting Day 2
UID:day2-001@example.com
END:VEVENT
END:VCALENDAR"""

        # Should find event with 7-day window
        events_7day = get_upcoming_events(test_ical, days_ahead=7)
        assert len(events_7day) == 1

        # Should NOT find event with 1-day window
        events_1day = get_upcoming_events(test_ical, days_ahead=1)
        assert len(events_1day) == 0


class TestValidation:
    """Test validation functions"""

    def test_validate_environment_variables_success(self):
        """Test successful environment variable validation"""
        with patch.dict(os.environ, {
            'S3_BUCKET_NAME': 'test-bucket',
            'SCHEDULE_GROUP_NAME': 'test-group'
        }):
            bucket, group, errors = validate_environment_variables()
            assert bucket == 'test-bucket'
            assert group == 'test-group'
            assert errors == []

    def test_validate_environment_variables_missing(self):
        """Test missing environment variables"""
        with patch.dict(os.environ, {}, clear=True):
            bucket, group, errors = validate_environment_variables()
            assert bucket is None
            assert group is None
            assert len(errors) == 2
            assert 'S3_BUCKET_NAME' in errors[0]
            assert 'SCHEDULE_GROUP_NAME' in errors[1]

    def test_validate_event_payload_success(self):
        """Test successful event payload validation"""
        event = {'zip_file': 'base64data'}
        zip_data, errors = validate_event_payload(event)
        assert zip_data == 'base64data'
        assert errors == []

    def test_validate_event_payload_missing(self):
        """Test missing zip_file in event payload"""
        event = {}
        zip_data, errors = validate_event_payload(event)
        assert zip_data is None
        assert len(errors) == 1
        assert 'zip_file required' in errors[0]


class TestZipProcessing:
    """Test zip file processing functions"""

    def test_decode_zip_file(self):
        """Test base64 zip file decoding"""
        # Create test zip in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr('test.txt', 'test content')

        # Encode to base64
        zip_data = zip_buffer.getvalue()
        zip_b64 = base64.b64encode(zip_data).decode('utf-8')

        # Test decode
        result = decode_zip_file(zip_b64)
        assert isinstance(result, io.BytesIO)
        assert result.getvalue() == zip_data

    def test_extract_ical_files_from_zip(self):
        """Test extracting .ics files from zip"""
        # Create test zip with .ics files
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr('calendar1.ics', 'BEGIN:VCALENDAR\nEND:VCALENDAR')
            zf.writestr('calendar2.ics', 'BEGIN:VCALENDAR\nEND:VCALENDAR')
            zf.writestr('readme.txt', 'not a calendar file')
            zf.writestr('folder/', '')  # Directory entry

        zip_buffer.seek(0)

        ical_files = extract_ical_files_from_zip(zip_buffer)

        assert len(ical_files) == 2
        filenames = [f[0] for f in ical_files]
        assert 'calendar1.ics' in filenames
        assert 'calendar2.ics' in filenames
        assert 'readme.txt' not in filenames

    @mock_aws
    def test_upload_ical_file_to_s3(self):
        """Test uploading iCal file to S3"""
        # Create mock S3 bucket
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket='test-bucket')

        content = b'BEGIN:VCALENDAR\nEND:VCALENDAR'
        upload_ical_file_to_s3(s3, content, 'test-bucket', 'test.ics')

        # Verify file was uploaded
        response = s3.get_object(Bucket='test-bucket', Key='test.ics')
        assert response['Body'].read() == content
        assert response['ContentType'] == 'text/calendar'


class TestS3Operations:
    """Test S3-related functions"""

    @mock_aws
    def test_list_ical_files_in_bucket(self):
        """Test listing .ics files in S3 bucket"""
        # Create mock S3 bucket with files
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket='test-bucket')

        # Upload test files
        s3.put_object(Bucket='test-bucket', Key='calendar1.ics', Body=b'test')
        s3.put_object(Bucket='test-bucket', Key='calendar2.ics', Body=b'test')
        s3.put_object(Bucket='test-bucket', Key='readme.txt', Body=b'test')

        files = list_ical_files_in_bucket(s3, 'test-bucket')

        assert len(files) == 2
        assert 'calendar1.ics' in files
        assert 'calendar2.ics' in files
        assert 'readme.txt' not in files

    @mock_aws
    def test_list_ical_files_empty_bucket(self):
        """Test listing files in empty bucket"""
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket='empty-bucket')

        files = list_ical_files_in_bucket(s3, 'empty-bucket')
        assert files == []

    @mock_aws
    def test_download_ical_content(self):
        """Test downloading iCal content from S3"""
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket='test-bucket')

        test_content = b'BEGIN:VCALENDAR\nEND:VCALENDAR'
        s3.put_object(Bucket='test-bucket', Key='test.ics', Body=test_content)

        content = download_ical_content(s3, 'test-bucket', 'test.ics')
        assert content == test_content


class TestScheduleUtilities:
    """Test schedule-related utility functions"""

    def test_generate_schedule_name(self):
        """Test generating unique schedule names"""
        event = {
            'uid': 'test-event-123',
            'start_datetime': datetime(2023, 12, 25, 10, 0, 0)
        }

        name = generate_schedule_name(event)
        expected_timestamp = int(event['start_datetime'].timestamp())
        expected_name = f"event-test-event-123-{expected_timestamp}"

        assert name == expected_name

    def test_calculate_notification_time(self):
        """Test calculating notification time"""
        event_time = datetime(2023, 12, 25, 10, 0, 0)
        notification_time = calculate_notification_time(event_time, 15)

        expected_time = datetime(2023, 12, 25, 9, 45, 0)
        assert notification_time == expected_time

    def test_build_schedule_payload(self):
        """Test building schedule payload"""
        event = {
            'summary': 'Test Meeting',
            'location': 'Conference Room',
            'start_datetime': datetime(2023, 12, 25, 10, 0, 0)
        }

        payload = build_schedule_payload(event)
        payload_data = json.loads(payload)

        assert payload_data['event_summary'] == 'Test Meeting'
        assert payload_data['event_location'] == 'Conference Room'
        assert payload_data['event_time'] == '2023-12-25T10:00:00'
        assert payload_data['notification_type'] == 'calendar_reminder'

    def test_get_schedule_configuration_success(self):
        """Test successful schedule configuration retrieval"""
        with patch.dict(os.environ, {
            'NOTIFICATION_LAMBDA_ARN': 'arn:aws:lambda:us-east-1:123456789012:function:notify',
            'SCHEDULER_ROLE_ARN': 'arn:aws:iam::123456789012:role/scheduler',
            'NOTIFICATION_MINUTES_BEFORE': '30'
        }):
            lambda_arn, role_arn, minutes, timezone = get_schedule_configuration()
            assert lambda_arn == 'arn:aws:lambda:us-east-1:123456789012:function:notify'
            assert role_arn == 'arn:aws:iam::123456789012:role/scheduler'
            assert minutes == 30
            assert timezone == 'UTC'

    def test_get_schedule_configuration_missing_vars(self):
        """Test schedule configuration with missing environment variables"""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError) as exc_info:
                get_schedule_configuration()
            assert 'NOTIFICATION_LAMBDA_ARN' in str(exc_info.value)


class TestTimezoneHandling:
    """Test timezone-related functionality"""

    def test_get_schedule_configuration_with_fallback_timezone(self):
        """Test schedule configuration includes fallback timezone"""
        with patch.dict(os.environ, {
            'NOTIFICATION_LAMBDA_ARN': 'arn:aws:lambda:us-east-1:123456789012:function:notify',
            'SCHEDULER_ROLE_ARN': 'arn:aws:iam::123456789012:role/scheduler',
            'NOTIFICATION_MINUTES_BEFORE': '30',
            'FALLBACK_TIMEZONE': 'Australia/Melbourne'
        }):
            lambda_arn, role_arn, minutes, timezone = get_schedule_configuration()
            assert timezone == 'Australia/Melbourne'

    def test_get_schedule_configuration_default_fallback_timezone(self):
        """Test default fallback timezone when not specified"""
        with patch.dict(os.environ, {
            'NOTIFICATION_LAMBDA_ARN': 'arn:aws:lambda:us-east-1:123456789012:function:notify',
            'SCHEDULER_ROLE_ARN': 'arn:aws:iam::123456789012:role/scheduler',
        }):
            lambda_arn, role_arn, minutes, timezone = get_schedule_configuration()
            assert timezone == 'UTC'

    @mock_aws
    @patch('lambda_function.datetime')
    def test_create_event_schedule_with_timezone_aware_event(self, mock_datetime):
        """Test creating schedule for timezone-aware event"""
        # Setup mock current time
        current_utc = datetime(2024, 12, 20, 10, 0, 0, tzinfo=pytz.UTC)
        mock_datetime.now.return_value = current_utc

        # Setup environment
        with patch.dict(os.environ, {
            'NOTIFICATION_LAMBDA_ARN': 'arn:aws:lambda:us-east-1:123456789012:function:notify',
            'SCHEDULER_ROLE_ARN': 'arn:aws:iam::123456789012:role/scheduler',
            'SCHEDULE_GROUP_NAME': 'test-group',
            'FALLBACK_TIMEZONE': 'Australia/Melbourne'
        }):
            # Setup EventBridge scheduler
            scheduler = boto3.client('scheduler', region_name='us-east-1')
            scheduler.create_schedule_group(Name='test-group')

            # Create timezone-aware event
            sydney_tz = pytz.timezone('Australia/Sydney')
            event_time = sydney_tz.localize(datetime(2024, 12, 25, 10, 0, 0))

            event = {
                'summary': 'Sydney Meeting',
                'start_datetime': event_time,
                'location': 'Sydney Office',
                'description': '',
                'uid': 'sydney-meeting-001'
            }

            # This should work without raising an exception
            create_event_schedule(event, 'test-group')

    @mock_aws
    @patch('lambda_function.datetime')
    def test_create_event_schedule_with_naive_datetime(self, mock_datetime):
        """Test creating schedule for naive datetime uses fallback timezone"""
        # Setup mock current time - return naive time for naive comparison
        current_naive = datetime(2024, 12, 20, 10, 0, 0)
        mock_datetime.now.return_value = current_naive

        # Setup environment
        with patch.dict(os.environ, {
            'NOTIFICATION_LAMBDA_ARN': 'arn:aws:lambda:us-east-1:123456789012:function:notify',
            'SCHEDULER_ROLE_ARN': 'arn:aws:iam::123456789012:role/scheduler',
            'SCHEDULE_GROUP_NAME': 'test-group',
            'FALLBACK_TIMEZONE': 'America/New_York'
        }):
            # Setup EventBridge scheduler
            scheduler = boto3.client('scheduler', region_name='us-east-1')
            scheduler.create_schedule_group(Name='test-group')

            # Create naive datetime event (no timezone)
            event_time = datetime(2024, 12, 25, 10, 0, 0)  # No timezone

            event = {
                'summary': 'NYC Meeting',
                'start_datetime': event_time,
                'location': 'NYC Office',
                'description': '',
                'uid': 'nyc-meeting-001'
            }

            # This should work and use fallback timezone
            create_event_schedule(event, 'test-group')

    @mock_aws
    @patch('lambda_function.datetime')
    def test_create_event_schedule_skips_past_events(self, mock_datetime):
        """Test that past events are skipped"""
        # Setup mock current time
        current_utc = datetime(2024, 12, 25, 12, 0, 0, tzinfo=pytz.UTC)
        mock_datetime.now.return_value = current_utc

        # Setup environment
        with patch.dict(os.environ, {
            'NOTIFICATION_LAMBDA_ARN': 'arn:aws:lambda:us-east-1:123456789012:function:notify',
            'SCHEDULER_ROLE_ARN': 'arn:aws:iam::123456789012:role/scheduler',
            'SCHEDULE_GROUP_NAME': 'test-group',
            'NOTIFICATION_MINUTES_BEFORE': '15'
        }):
            # Create past event (before current time)
            past_time = datetime(2024, 12, 25, 10, 0, 0, tzinfo=pytz.UTC)  # 2 hours ago

            event = {
                'summary': 'Past Meeting',
                'start_datetime': past_time,
                'location': '',
                'description': '',
                'uid': 'past-meeting-001'
            }

            # Should not raise exception, just skip the event
            result = create_event_schedule(event, 'test-group')
            assert result is None  # Function returns None for skipped events

    def test_ical_with_timezone_events(self):
        """Test parsing iCal content with timezone-aware events"""
        # Create iCal with timezone info
        future_date = datetime.now() + timedelta(days=2)
        future_str = future_date.strftime("%Y%m%dT%H%M%S")

        test_ical = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VTIMEZONE
TZID:Australia/Melbourne
BEGIN:STANDARD
DTSTART:20240407T030000
RRULE:FREQ=YEARLY;BYMONTH=4;BYDAY=1SU
TZNAME:AEST
TZOFFSETFROM:+1100
TZOFFSETTO:+1000
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:20241006T020000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=1SU
TZNAME:AEDT
TZOFFSETFROM:+1000
TZOFFSETTO:+1100
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VEVENT
DTSTART;TZID=Australia/Melbourne:{future_str}
DTEND;TZID=Australia/Melbourne:{future_str.replace('T10', 'T11')}
SUMMARY:Melbourne Meeting
LOCATION:Melbourne Office
UID:melbourne-001@example.com
END:VEVENT
END:VCALENDAR"""

        events = get_upcoming_events(test_ical, days_ahead=7)

        assert len(events) == 1
        assert events[0]['summary'] == 'Melbourne Meeting'
        assert events[0]['location'] == 'Melbourne Office'
        # The recurring_ical_events library should handle timezone conversion


class TestLambdaHandler:
    """Test the main lambda handler function"""

    @mock_aws
    def test_lambda_handler_success(self):
        """Test successful lambda handler execution"""
        # Set up environment
        with patch.dict(os.environ, {
            'S3_BUCKET_NAME': 'test-bucket',
            'SCHEDULE_GROUP_NAME': 'test-group',
            'NOTIFICATION_LAMBDA_ARN': 'arn:aws:lambda:us-east-1:123456789012:function:notify',
            'SCHEDULER_ROLE_ARN': 'arn:aws:iam::123456789012:role/scheduler'
        }):
            # Create S3 bucket and scheduler group
            s3 = boto3.client('s3', region_name='us-east-1')
            s3.create_bucket(Bucket='test-bucket')

            scheduler = boto3.client('scheduler', region_name='us-east-1')

            # Create test zip file with iCal content
            tomorrow = datetime.now() + timedelta(days=1)
            tomorrow_str = tomorrow.strftime("%Y%m%dT%H%M%SZ")

            test_ical = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
DTSTART:{tomorrow_str}
DTEND:{tomorrow_str.replace('T10', 'T11')}
SUMMARY:Test Meeting
UID:test-001@example.com
END:VEVENT
END:VCALENDAR"""

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w') as zf:
                zf.writestr('test.ics', test_ical)

            zip_b64 = base64.b64encode(zip_buffer.getvalue()).decode('utf-8')

            event = {'zip_file': zip_b64}
            context = {}

            result = lambda_handler(event, context)

            assert result['success'] is True
            assert result['calendars_processed'] == 1
            assert result['total_events'] == 1

    def test_lambda_handler_missing_env_vars(self):
        """Test lambda handler with missing environment variables"""
        with patch.dict(os.environ, {}, clear=True):
            event = {'zip_file': 'test'}
            context = {}

            result = lambda_handler(event, context)

            assert result['success'] is False
            assert 'S3_BUCKET_NAME' in result['error']

    def test_lambda_handler_missing_zip_file(self):
        """Test lambda handler with missing zip file"""
        with patch.dict(os.environ, {
            'S3_BUCKET_NAME': 'test-bucket',
            'SCHEDULE_GROUP_NAME': 'test-group'
        }):
            event = {}
            context = {}

            result = lambda_handler(event, context)

            assert result['success'] is False
            assert 'zip_file required' in result['error']