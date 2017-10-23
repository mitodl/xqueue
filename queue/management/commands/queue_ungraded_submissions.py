import logging

from django.core.management.base import BaseCommand
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from datetime import datetime, timedelta
import pprint

from queue.models import Submission
from queue.producer import push_to_queue

log = logging.getLogger(__name__)


def parse_iso_8601_string(iso_string):
    return datetime.strptime(iso_string, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


class Command(BaseCommand):
    help = "Push ungraded submissions onto the queue for grading. Useful for cases where grading fails."
    ECHO_LIMIT = 25
    ECHO_PROPERTIES = ('id', 'queue_name', 'push_time', 'pull_time', 'return_time', 'num_failures', 'lms_callback_url')

    def add_arguments(self, parser):
        parser.add_argument(
            '--queues',
            dest='queue_names',
            default='',
            help='Names of queues (comma-separated)',
        )
        parser.add_argument(
            '--ids',
            dest='submission_ids',
            default='',
            help='Submission.id values (comma-separated)',
        )
        parser.add_argument(
            '--pull-time-start',
            dest='pull_time_start',
            default=None,
            help='Submission pull_time range start (UTC, ISO-8601 formatted - 2017-01-01T00:00:00Z, et. al.)',
        )
        parser.add_argument(
            '--pull-time-end',
            dest='pull_time_end',
            default=None,
            help='Submission pull_time range end (UTC, ISO-8601 formatted - 2017-01-01T00:00:00Z, et. al.)',
        )
        parser.add_argument(
            '--ignore-failures',
            action='store_true',
            dest='ignore_failures',
            default=False,
            help='Requeue the submissions even if their num_failures is greater than the max in settings',
        )
        parser.add_argument(
            '--echo',
            action='store_true',
            dest='echo',
            default=False,
            help='Echo the submissions that will be queued for grading (instead of actually queueing them)',
        )

    def handle(self, *args, **options):
        query_exclude_params = dict(
            lms_ack=1,
            retired=1
        )
        query_param_dict = {}
        query_param_list = []
        if options['queue_names']:
            query_param_dict['queue_name__in'] = options['queue_names'].split(',')
        if options['submission_ids']:
            query_param_dict['id__in'] = options['submission_ids'].split(',')
        if options['pull_time_start']:
            query_param_dict['pull_time__gte'] = parse_iso_8601_string(options['pull_time_start'])
        if options['pull_time_end']:
            query_param_dict['pull_time__lte'] = parse_iso_8601_string(options['pull_time_end'])
            query_exclude_params['pull_time'] = None
        else:
            query_param_list.append(
                Q(pull_time__lte=timezone.now() - timedelta(seconds=settings.PULLED_SUBMISSION_TIMEOUT)) |
                Q(pull_time=None)
            )
        if not options['ignore_failures']:
            query_param_dict['num_failures__lt'] = settings.MAX_NUMBER_OF_FAILURES

        submission_qset = (
            Submission.objects
            .filter(*query_param_list, **query_param_dict)
            .exclude(**query_exclude_params)
            .order_by('-push_time')
        )
        if options['echo']:
            pp = pprint.PrettyPrinter(indent=2)
            for submission in submission_qset.values(*self.ECHO_PROPERTIES)[0:self.ECHO_LIMIT]:
                self.stdout.write(pp.pformat(submission))
            num_submissions = submission_qset.count()
            self.stdout.write("\nMatching submission count: {0}".format(num_submissions))
            if num_submissions > self.ECHO_LIMIT:
                submission_ids = submission_qset.values_list('id', flat=True)
                self.stdout.write("\nIDs: {0}\n\n".format(','.join(map(str, submission_ids))))
        else:
            self.requeue_submissions(submission_qset)
    
    def requeue_submissions(self, submission_qset):
        num_submissions = submission_qset.count()
        if num_submissions == 0:
            self.stdout.write("No matching submissions to queue.")
            return
        self.stdout.write("Queueing {0} submissions...".format(num_submissions))
        for submission in submission_qset:
            if submission.pull_time:
                submission.num_failures += 1
                submission.pull_time = None
                submission.pullkey = ''
                submission.save()
            push_to_queue(submission.queue_name, str(submission.id))
        self.stdout.write("Queueing finished")
