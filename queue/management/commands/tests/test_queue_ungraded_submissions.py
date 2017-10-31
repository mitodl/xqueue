import mock
from unittest import TestCase
from django.conf import settings
from django.core.management import call_command
from django.utils.six import StringIO


class TestQueueUngradedSubmissions(TestCase):
    def setUpClass(cls):
        cls.stdout = StringIO()

    def setUp(self):
        patcher = mock.patch('queue.producer.push_to_queue')
        self.mock_push_to_queue = patcher.start()

    def tearDown(self):
        self.mock_push_to_queue.stop()

    def test_queues_param(self):
        call_command(
            'queue_ungraded_submissions',
            queue_names='queue1,queue2',
            stdout=self.stdout
        )
