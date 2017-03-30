"""Tests for certbot.log."""
import logging
import logging.handlers
import os
import sys
import tempfile
import time
import unittest

import mock
import six

from acme import messages

from certbot import constants
from certbot import errors
from certbot import util
from certbot.tests import util as test_util


class PreArgSetupTest(unittest.TestCase):
    """Tests for certbot.log.pre_arg_setup."""

    @classmethod
    def _call(cls, *args, **kwargs):
        from certbot.log import pre_arg_setup
        return pre_arg_setup(*args, **kwargs)

    def test_it(self):
        with mock.patch('certbot.log.util.atexit_register') as mock_register:
            with mock.patch('certbot.log.logging.getLogger') as mock_get:
                with mock.patch('certbot.log.except_hook') as mock_except_hook:
                    with mock.patch('certbot.log.sys') as mock_sys:
                        mock_sys.argv = ['--debug']
                        self._call()

        mock_register.assert_called_once_with(logging.shutdown)
        mock_sys.excepthook(1, 2, 3)
        mock_except_hook.assert_called_once_with(
            1, 2, 3, debug=True, log_path=mock.ANY)

        mock_root_logger = mock_get()
        mock_root_logger.setLevel.assert_called_once_with(logging.DEBUG)
        self.assertEqual(mock_root_logger.addHandler.call_count, 2)

        MemoryHandler = logging.handlers.MemoryHandler
        memory_handler = None
        for call in mock_root_logger.addHandler.call_args_list:
            handler = call[0][0]
            if memory_handler is None and isinstance(handler, MemoryHandler):
                memory_handler = handler
            else:
                self.assertTrue(isinstance(handler, logging.StreamHandler))
        self.assertTrue(
            isinstance(memory_handler.target, logging.StreamHandler))
        temp_file = memory_handler.target.stream.name
        self.assertTrue(
            util.check_permissions(temp_file, 0o600, os.getuid()))


class PostArgSetupTest(test_util.TempDirTestCase):
    """Tests for certbot.log.post_arg_setup."""

    @classmethod
    def _call(cls, *args, **kwargs):
        from certbot.log import post_arg_setup
        return post_arg_setup(*args, **kwargs)

    def setUp(self):
        super(PostArgSetupTest, self).setUp()
        self.config = mock.MagicMock(
            debug=False, logs_dir=self.tempdir, quiet=False,
            verbose_count=constants.CLI_DEFAULTS['verbose_count'])
        self.devnull = open(os.devnull, 'w')

        self.temp_file = tempfile.NamedTemporaryFile('w', delete=False)
        temp_handler = logging.StreamHandler(self.temp_file)

        from certbot.log import ColoredStreamHandler, MemoryHandler
        self.memory_handler = MemoryHandler(temp_handler)
        self.stream_handler = ColoredStreamHandler(self.devnull)
        self.root_logger = mock.MagicMock(
            handlers=[self.memory_handler, self.stream_handler])

    def tearDown(self):
        self.devnull.close()
        super(PostArgSetupTest, self).tearDown()

    def test_common(self):
        with mock.patch('certbot.log.logging.getLogger') as mock_get_logger:
            mock_get_logger.return_value = self.root_logger
            with mock.patch('certbot.log.except_hook') as mock_except_hook:
                with mock.patch('certbot.log.sys') as mock_sys:
                    self._call(self.config)

        self.root_logger.removeHandler.assert_called_once_with(
            self.memory_handler)
        self.assertTrue(self.root_logger.addHandler.called)
        self.assertTrue(os.path.exists(os.path.join(
            self.config.logs_dir, 'letsencrypt.log')))
        self.assertFalse(os.path.exists(self.temp_file.name))
        mock_sys.excepthook(1, 2, 3)
        mock_except_hook.assert_called_once_with(
            1, 2, 3, debug=self.config.debug, log_path=self.tempdir)

        level = self.stream_handler.level
        if self.config.quiet:
            self.assertEqual(level, constants.QUIET_LOGGING_LEVEL)
        else:
            self.assertEqual(level, -self.config.verbose_count * 10)

    def test_debug(self):
        self.config.debug = True
        self.test_common()

    def test_quiet(self):
        self.config.quiet = True
        self.test_common()

    def test_reversed(self):
        self.root_logger.handlers.reverse()
        self.test_common()


class SetupLogFileHandlerTest(test_util.TempDirTestCase):
    """Tests for certbot.log.setup_log_file_handler."""

    @classmethod
    def _call(cls, *args, **kwargs):
        from certbot.log import setup_log_file_handler
        return setup_log_file_handler(*args, **kwargs)

    def setUp(self):
        super(SetupLogFileHandlerTest, self).setUp()

        self.config = mock.Mock(spec_set=['logs_dir'],
                                logs_dir=self.tempdir)

    def test_failure(self):
        self.config.logs_dir = os.path.join(self.config.logs_dir, 'test.log')
        open(self.config.logs_dir, 'w').close()

        try:
            self._call(self.config, 'test.log', '%(message)s')
        except errors.Error as err:
            self.assertTrue('--logs-dir' in str(err))
        else:  # pragma: no cover
            self.fail('Error not raised.')

    def test_success(self):
        log_file = 'test.log'
        handler, log_path = self._call(self.config, log_file, '%(message)s')
        self.assertEqual(handler.level, logging.DEBUG)
        self.assertEqual(handler.formatter.converter, time.gmtime)

        expected_path = os.path.join(self.config.logs_dir, log_file)
        self.assertEqual(log_path, expected_path)


class ColoredStreamHandlerTest(unittest.TestCase):
    """Tests for certbot.log.ColoredStreamHandler"""

    def setUp(self):
        self.stream = six.StringIO()
        self.stream.isatty = lambda: True
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.DEBUG)

        from certbot.log import ColoredStreamHandler
        self.handler = ColoredStreamHandler(self.stream)
        self.logger.addHandler(self.handler)

    def test_format(self):
        msg = 'I did a thing'
        self.logger.debug(msg)
        self.assertEqual(self.stream.getvalue(), '{0}\n'.format(msg))

    def test_format_and_red_level(self):
        msg = 'I did another thing'
        self.handler.red_level = logging.DEBUG
        self.logger.debug(msg)

        self.assertEqual(self.stream.getvalue(),
                         '{0}{1}{2}\n'.format(util.ANSI_SGR_RED,
                                              msg,
                                              util.ANSI_SGR_RESET))


class MemoryHandlerTest(unittest.TestCase):
    """Tests for certbot.log.MemoryHandler"""
    def setUp(self):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        self.msg = 'hi there'
        self.stream = six.StringIO()

        stream_handler = logging.StreamHandler(self.stream)
        from certbot.log import MemoryHandler
        self.handler = MemoryHandler(stream_handler)
        self.logger.addHandler(self.handler)

    def test_flush(self):
        self._test_log_debug()
        self.handler.flush()
        self.assertEqual(self.stream.getvalue(), self.msg + '\n')

    def test_not_flushed(self):
        # By default, logging.ERROR messages and higher are flushed
        self.logger.critical(self.msg)
        self.assertEqual(self.stream.getvalue(), '')

    def test_target_reset(self):
        self._test_log_debug()

        new_stream = six.StringIO()
        stream_handler = logging.StreamHandler(new_stream)
        self.handler.setTarget(stream_handler)
        self.handler.flush()
        self.assertEqual(self.stream.getvalue(), '')
        self.assertEqual(new_stream.getvalue(), self.msg + '\n')

    def _test_log_debug(self):
        self.logger.debug(self.msg)


class ExceptHookTest(unittest.TestCase):
    """Tests for certbot.log.except_hook."""
    @classmethod
    def _call(cls, *args, **kwargs):
        from certbot.log import except_hook
        return except_hook(*args, **kwargs)

    def setUp(self):
        self.error_msg = 'test error message'
        self.log_path = 'foo.log'

    def test_base_exception(self):
        mock_logger, output = self._test_common(KeyboardInterrupt, debug=False)
        self.assertTrue(mock_logger.exception.called)
        self._assert_logfile_output(output)

    def test_debug(self):
        mock_logger, output = self._test_common(ValueError, debug=True)
        self.assertTrue(mock_logger.exception.called)
        self._assert_logfile_output(output)

    def test_custom_error(self):
        mock_logger, output = self._test_common(
            errors.PluginError, debug=False)
        self._assert_quiet_output(mock_logger, output)

    def test_acme_error(self):
        # Get an arbitrary error code
        acme_code = next(six.iterkeys(messages.ERROR_CODES))

        def get_acme_error(msg):
            """Wraps ACME errors so the constructor takes only a msg."""
            return messages.Error.with_code(acme_code, detail=msg)

        mock_logger, output = self._test_common(get_acme_error, debug=False)
        self._assert_quiet_output(mock_logger, output)
        self.assertFalse(messages.ERROR_PREFIX in output)

    def test_other_error(self):
        mock_logger, output = self._test_common(ValueError, debug=False)
        self._assert_quiet_output(mock_logger, output)

    def _test_common(self, error_type, debug):
        """Returns the mocked logger and stderr output."""
        mock_err = six.StringIO()
        try:
            raise error_type(self.error_msg)
        except BaseException:
            exc_info = sys.exc_info()
            with mock.patch('certbot.log.logger') as mock_logger:
                with mock.patch('certbot.log.sys.stderr', mock_err):
                    try:
                        # pylint: disable=star-args
                        self._call(
                            *exc_info, debug=debug, log_path=self.log_path)
                    except SystemExit as exit_err:
                        mock_err.write(str(exit_err))
                    else:  # pragma: no cover
                        self.fail('SystemExit not raised.')

        output = mock_err.getvalue()
        return mock_logger, output

    def _assert_logfile_output(self, output):
        self.assertTrue('Please see the logfile' in output)
        self.assertTrue(self.log_path in output)

    def _assert_quiet_output(self, mock_logger, output):
        self.assertFalse(mock_logger.exception.called)
        self.assertTrue(mock_logger.debug.called)
        self.assertTrue(self.error_msg in output)


class ExitWithLogPathTest(test_util.TempDirTestCase):
    """Tests for certbot.log.exit_with_log_path."""
    @classmethod
    def _call(cls, *args, **kwargs):
        from certbot.log import exit_with_log_path
        return exit_with_log_path(*args, **kwargs)

    def test_log_file(self):
        log_file = os.path.join(self.tempdir, 'test.log')
        open(log_file, 'w').close()

        err_str = self._test_common(log_file)
        self.assertTrue('logfiles' not in err_str)
        self.assertTrue(log_file in err_str)

    def test_log_dir(self):
        err_str = self._test_common(self.tempdir)
        self.assertTrue('logfiles' in err_str)
        self.assertTrue(self.tempdir in err_str)

    def _test_common(self, *args, **kwargs):
        try:
            self._call(*args, **kwargs)
        except SystemExit as err:
            return str(err)
        else:  # pragma: no cover
            self.fail('SystemExit was not raised.')


if __name__ == "__main__":
    unittest.main()  # pragma: no cover