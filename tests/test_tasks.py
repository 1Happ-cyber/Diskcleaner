import threading
import time
import unittest
from diskcleaner.tasks import TaskRunner


class TaskRunnerTests(unittest.TestCase):
    def test_success_event(self):
        runner = TaskRunner()
        seen = []

        def work():
            seen.append(runner.cancel.is_set())
            return 42

        runner.start('demo', work)
        self.assertTrue(runner.join(2))
        self.assertFalse(runner.busy)
        events = runner.poll()
        self.assertEqual(events, [('done', 'demo', 42)])
        self.assertEqual(seen, [False])

    def test_error_is_reported(self):
        runner = TaskRunner()
        runner.start('demo', lambda: 1 / 0)
        runner.join(2)
        events = runner.poll()
        self.assertEqual(events[0][0], 'error')
        self.assertIn('ZeroDivisionError', events[0][2])

    def test_progress_messages_arrive_in_order(self):
        runner = TaskRunner()

        def work():
            runner.progress('一')
            runner.progress('二')
            return 'done'

        runner.start('demo', work)
        runner.join(2)
        payloads = [event[2] for event in runner.poll() if event[0] == 'progress']
        self.assertEqual(payloads, ['一', '二'])

    def test_busy_rejects_second_task(self):
        runner = TaskRunner()
        release = threading.Event()
        runner.start('slow', lambda: release.wait(2))
        with self.assertRaises(RuntimeError):
            runner.start('other', lambda: None)
        release.set()
        self.assertTrue(runner.join(2))

    def test_cancel_event_visible_to_operation(self):
        runner = TaskRunner()
        observed = []

        def work():
            for _ in range(100):
                if runner.cancel.is_set():
                    observed.append(True)
                    return 'cancelled'
                time.sleep(0.01)
            observed.append(False)
            return 'finished'

        runner.start('demo', work)
        runner.cancel.set()
        self.assertTrue(runner.join(2))
        self.assertEqual(observed, [True])

    def test_busy_cleared_after_polling(self):
        runner = TaskRunner()
        runner.start('demo', lambda: None)
        runner.join(2)
        runner.poll()
        self.assertFalse(runner.busy)
        self.assertFalse(runner.cancel.is_set())


if __name__ == '__main__':
    unittest.main()
